from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from harness.agent_package import pack_agent_package
from harness.release import create_release_manifest, write_release_manifest
from harness.release_deploy import ReleaseComposeDeployer


def manifest(tmp_path: Path, marker: str) -> Path:
    root = tmp_path / marker
    agents = root / "agents"
    agents.mkdir(parents=True)
    archive, _report = pack_agent_package(
        "agents/echo-agent/agent.yaml", output_directory=agents
    )
    sboms = root / "sbom"
    sboms.mkdir()
    for component in ("api", "web", "sandbox"):
        (sboms / f"{component}.json").write_text(
            json.dumps({"spdxVersion": "SPDX-2.3", "marker": marker}),
            encoding="utf-8",
        )
    value = create_release_manifest(
        artifact_root=root,
        source_commit=marker * 40,
        bundle_paths=(archive,),
        image_references={
            "api": f"registry/api@sha256:{marker * 64}",
            "web": f"registry/web@sha256:{marker * 64}",
            "sandbox": f"registry/sandbox@sha256:{marker * 64}",
        },
        sbom_paths={
            component: sboms / f"{component}.json"
            for component in ("api", "web", "sandbox")
        },
    )
    path = root / "release-manifest.json"
    write_release_manifest(value, path)
    return path


def test_apply_uses_digest_images_and_rollback_does_not_downgrade_database(
    tmp_path: Path,
) -> None:
    compose_env = tmp_path / "deployment.env"
    compose_env.write_text("POSTGRES_PASSWORD=not-a-real-secret\n", encoding="utf-8")
    commands: list[tuple[str, ...]] = []
    environments: list[dict[str, str]] = []

    def runner(command: Sequence[str], environment: Mapping[str, str]) -> None:
        commands.append(tuple(command))
        environments.append(dict(environment))

    deployer = ReleaseComposeDeployer(
        repository_root=Path.cwd(),
        compose_env_file=compose_env,
        state_root=tmp_path / "state",
        environment_name="canary",
        runner=runner,
    )
    deployer.apply(manifest(tmp_path, "a"))
    commands.clear()
    environments.clear()
    second = deployer.apply(manifest(tmp_path, "b"))

    assert all("@sha256:" in environment["HARNESS_API_IMAGE"] for environment in environments)
    assert any(command[-3:] == ("run", "--rm", "migrate") for command in commands)
    assert (tmp_path / "state/canary/current.json").is_file()
    assert (tmp_path / "state/canary/previous.json").is_file()

    commands.clear()
    restored = deployer.rollback()

    assert restored.release_id != second.release_id
    assert not any(command[-3:] == ("run", "--rm", "migrate") for command in commands)
    assert any("up" in command and "--no-build" in command for command in commands)
