from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import httpx
import pytest

from harness.agent_package import pack_agent_package
from harness.promotion import PromotionError, PromotionPlan, ReleasePromotionClient
from harness.release import ReleaseManifest, create_release_manifest


def release(tmp_path: Path) -> tuple[Path, ReleaseManifest]:
    root = tmp_path / "release"
    agents = root / "agents"
    agents.mkdir(parents=True)
    archive, _report = pack_agent_package(
        "agents/echo-agent/agent.yaml", output_directory=agents
    )
    sboms = root / "sbom"
    sboms.mkdir()
    for component in ("api", "web", "sandbox"):
        (sboms / f"{component}.json").write_text(
            json.dumps({"spdxVersion": "SPDX-2.3"}), encoding="utf-8"
        )
    manifest = create_release_manifest(
        artifact_root=root,
        source_commit="a" * 40,
        bundle_paths=(archive,),
        image_references={
            "api": f"registry/api@sha256:{'a' * 64}",
            "web": f"registry/web@sha256:{'b' * 64}",
            "sandbox": f"registry/sandbox@sha256:{'c' * 64}",
        },
        sbom_paths={
            component: sboms / f"{component}.json"
            for component in ("api", "web", "sandbox")
        },
    )
    return root, manifest


def test_promote_checks_hashes_gates_and_pins_signed_image(tmp_path: Path) -> None:
    root, manifest = release(tmp_path)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = request.url.path
        if path == "/v1/agents/bundles":
            bundle = manifest.agent_bundles[0]
            return httpx.Response(
                201,
                json={
                    "name": bundle.name,
                    "version": bundle.version,
                    "manifest_hash": bundle.manifest_hash,
                    "package_hash": bundle.package_hash,
                },
            )
        if path.endswith("/quality-gate") or "/evaluation-gates/" in path:
            return httpx.Response(200, json={"passed": True})
        if path.endswith("/deployment-snapshots"):
            bundle = manifest.agent_bundles[0]
            return httpx.Response(
                200,
                json=[
                    {
                        "snapshotId": "snapshot-test",
                        "agentVersion": bundle.version,
                        "packageHash": bundle.package_hash,
                        "imageDigest": f"sha256:{'c' * 64}",
                        "config": {"RELEASE_ID": manifest.release_id},
                    }
                ],
            )
        if path.endswith("/environments"):
            return httpx.Response(
                200,
                json=[
                    {
                        "name": "test",
                        "revision": 8,
                        "healthySnapshotId": "snapshot-test",
                    },
                    {
                        "name": "canary",
                        "revision": 4,
                        "healthySnapshotId": "snapshot-old",
                    }
                ],
            )
        if path == "/v1/studio/deployments/promote":
            body = cast(dict[str, object], json.loads(request.content))
            assert body["imageDigest"] == f"sha256:{'c' * 64}"
            assert body["expectedEnvironmentRevision"] == 4
            return httpx.Response(
                202,
                json={
                    "deployment": {
                        "deploymentId": "deployment-new",
                        "previousSnapshotId": "snapshot-old",
                        "targetSnapshotId": "snapshot-new",
                    }
                },
            )
        if path == "/v1/studio/deployments/deployment-new":
            return httpx.Response(
                200,
                json={
                    "deployment": {
                        "deploymentId": "deployment-new",
                        "status": "succeeded",
                        "previousSnapshotId": "snapshot-old",
                        "targetSnapshotId": "snapshot-new",
                    },
                    "target": {"imageDigest": f"sha256:{'c' * 64}"},
                },
            )
        raise AssertionError(path)

    http = httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://harness.test"
    )
    client = ReleasePromotionClient(
        base_url="https://harness.test",
        service_token="x" * 32,
        tenant_id="tenant-a",
        user_id="release-bot",
        client=http,
        poll_seconds=0,
    )

    plan = client.promote(
        artifact_root=root,
        manifest=manifest,
        environment="canary",
        execution_profile="isolated-default",
        canary_percent=10,
    )

    assert plan.release_id == manifest.release_id
    assert plan.entries[0].previous_snapshot_id == "snapshot-old"
    assert all(request.headers["x-harness-service-token"] == "x" * 32 for request in requests)


def test_promotion_stops_before_environment_when_eval_gate_fails(tmp_path: Path) -> None:
    root, manifest = release(tmp_path)
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/v1/agents/bundles":
            bundle = manifest.agent_bundles[0]
            return httpx.Response(
                201,
                json={
                    "name": bundle.name,
                    "version": bundle.version,
                    "manifest_hash": bundle.manifest_hash,
                    "package_hash": bundle.package_hash,
                },
            )
        return httpx.Response(200, json={"passed": False})

    http = httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://harness.test"
    )
    client = ReleasePromotionClient(
        base_url="https://harness.test",
        service_token="x" * 32,
        tenant_id="tenant-a",
        user_id="release-bot",
        client=http,
        poll_seconds=0,
    )

    with pytest.raises(PromotionError, match="Eval gate blocked"):
        client.promote(
            artifact_root=root,
            manifest=manifest,
            environment="test",
            execution_profile="isolated-default",
            canary_percent=10,
        )

    assert not any(path.endswith("/environments") for path in paths)


def test_partial_promotion_rolls_back_before_returning_failure(tmp_path: Path) -> None:
    root, manifest = release(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        bundle = manifest.agent_bundles[0]
        if path == "/v1/agents/bundles":
            return httpx.Response(
                201,
                json={
                    "name": bundle.name,
                    "version": bundle.version,
                    "manifest_hash": bundle.manifest_hash,
                    "package_hash": bundle.package_hash,
                },
            )
        if path.endswith("/quality-gate") or "/evaluation-gates/" in path:
            return httpx.Response(200, json={"passed": True})
        if path.endswith("/environments"):
            return httpx.Response(
                200,
                json=[
                    {
                        "name": "test",
                        "revision": 1,
                        "healthySnapshotId": "snapshot-old",
                    }
                ],
            )
        if path == "/v1/studio/deployments/promote":
            return httpx.Response(
                202,
                json={
                    "deployment": {
                        "deploymentId": "deployment-new",
                        "previousSnapshotId": "snapshot-old",
                        "targetSnapshotId": "snapshot-new",
                    }
                },
            )
        if path == "/v1/studio/deployments/deployment-new":
            return httpx.Response(
                200,
                json={
                    "deployment": {"status": "succeeded"},
                    "target": {"imageDigest": f"sha256:{'d' * 64}"},
                },
            )
        raise AssertionError(path)

    class TrackingClient(ReleasePromotionClient):
        rolled_back = False

        def rollback(self, plan: PromotionPlan) -> PromotionPlan:
            self.rolled_back = True
            return plan

    http = httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://harness.test"
    )
    client = TrackingClient(
        base_url="https://harness.test",
        service_token="x" * 32,
        tenant_id="tenant-a",
        user_id="release-bot",
        client=http,
        poll_seconds=0,
    )

    with pytest.raises(PromotionError, match="changed the signed"):
        client.promote(
            artifact_root=root,
            manifest=manifest,
            environment="test",
            execution_profile="isolated-default",
            canary_percent=100,
        )

    assert client.rolled_back is True
