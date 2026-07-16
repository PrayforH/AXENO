from __future__ import annotations

import re
from pathlib import Path
from typing import cast

import yaml


def workflow(name: str) -> str:
    path = Path(".github/workflows") / name
    text = path.read_text(encoding="utf-8")
    assert isinstance(yaml.safe_load(text), dict)
    return text


def test_external_actions_are_pinned_to_full_commit_hashes() -> None:
    for name in ("verify.yml", "release.yml", "promote.yml"):
        for reference in re.findall(
            r"^\s*(?:-\s*)?uses:\s*([^\s#]+)", workflow(name), re.MULTILINE
        ):
            if reference.startswith("./"):
                continue
            assert re.fullmatch(r"[^@]+@[a-f0-9]{40}", reference), reference


def test_ci_blocks_package_eval_migration_and_vulnerability_failures() -> None:
    verify = workflow("verify.yml")

    for required in (
        "make verify",
        "scripts/e2e_fake_runtime.py",
        "tests/unit/evals",
        "alembic downgrade -1",
        "--severity HIGH,CRITICAL --exit-code 1",
        "cosign verify",
    ):
        assert required in verify
    makefile = Path("Makefile").read_text(encoding="utf-8")
    assert "verify: lint typecheck agent-check agent-determinism readiness test" in makefile


def test_release_builds_once_and_emits_signed_hash_and_sbom_evidence() -> None:
    release = workflow("release.yml")

    assert release.count("uses: docker/build-push-action@") == 3
    assert release.count("uses: anchore/sbom-action@") == 3
    assert "provenance: mode=max" in release
    assert "scripts/release_manifest.py create" in release
    assert "cosign attest" in release
    assert "cosign sign-blob" in release
    assert "release-${{ github.sha }}" in release


def test_promotion_never_rebuilds_and_has_stop_and_rollback_gates() -> None:
    promote = workflow("promote.yml")

    assert "docker build" not in promote
    assert "build-push-action" not in promote
    assert "scripts/release_manifest.py verify" in promote
    assert "scripts/deploy_release.py apply" in promote
    assert "scripts/promote_release.py promote" in promote
    assert "scripts/promote_release.py rollback" in promote
    assert "scripts/deploy_release.py rollback" in promote
    assert "cancel-in-progress: false" in promote
    assert "environment: ${{ inputs.environment }}" in promote


def test_release_compose_overlay_contains_only_digest_injected_images() -> None:
    overlay = Path("deploy/docker-compose/compose.release.yaml").read_text(encoding="utf-8")
    parsed = yaml.safe_load(overlay)

    assert isinstance(parsed, dict)
    assert "build:" not in overlay
    assert "HARNESS_API_IMAGE" in overlay
    assert "HARNESS_WEB_IMAGE" in overlay
    document = cast(dict[str, object], parsed)
    services = cast(dict[str, dict[str, str]], document["services"])
    assert services["migrate"]["image"] == services["seed"]["image"]
