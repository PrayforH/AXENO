from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.agent_package import pack_agent_package
from harness.release import (
    ReleaseManifest,
    create_release_manifest,
    load_release_manifest,
    verify_release_manifest,
    write_release_manifest,
)
from scripts.verify_agent_determinism import verify


def _release_root(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "release"
    agents = root / "agents"
    agents.mkdir(parents=True)
    archive, _report = pack_agent_package(
        "agents/echo-agent/agent.yaml", output_directory=agents
    )
    sboms = root / "sbom"
    sboms.mkdir()
    for component in ("api", "web", "sandbox"):
        (sboms / f"{component}.spdx.json").write_text(
            json.dumps({"spdxVersion": "SPDX-2.3", "name": component}),
            encoding="utf-8",
        )
    return root, archive


def _manifest(root: Path, archive: Path) -> ReleaseManifest:
    return create_release_manifest(
        artifact_root=root,
        source_commit="a" * 40,
        bundle_paths=(archive,),
        image_references={
            component: f"ghcr.io/example/harness-{component}@sha256:{index * 64}"
            for component, index in (("api", "a"), ("web", "b"), ("sandbox", "c"))
        },
        sbom_paths={
            component: root / "sbom" / f"{component}.spdx.json"
            for component in ("api", "web", "sandbox")
        },
    )


def test_release_manifest_is_deterministic_and_verifies_all_artifacts(
    tmp_path: Path,
) -> None:
    root, archive = _release_root(tmp_path)
    first = _manifest(root, archive)
    second = _manifest(root, archive)
    path = root / "release-manifest.json"

    write_release_manifest(first, path)
    loaded = load_release_manifest(path)
    verify_release_manifest(loaded, artifact_root=root, expected_commit="a" * 40)

    assert first == second == loaded
    assert loaded.agent_bundles[0].name == "echo-agent"
    assert {image.component for image in loaded.images} == {"api", "web", "sandbox"}


def test_release_manifest_rejects_changed_bundle_and_sbom(tmp_path: Path) -> None:
    root, archive = _release_root(tmp_path)
    manifest = _manifest(root, archive)
    archive.write_bytes(archive.read_bytes() + b"tampered")

    with pytest.raises(ValueError):
        verify_release_manifest(manifest, artifact_root=root)

    root, archive = _release_root(tmp_path / "sbom-case")
    manifest = _manifest(root, archive)
    (root / "sbom/api.spdx.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="SBOM"):
        verify_release_manifest(manifest, artifact_root=root)


def test_every_reference_agent_bundle_is_byte_deterministic() -> None:
    hashes = verify(Path("agents"))

    assert len(hashes) == 7
