import os
from datetime import UTC, datetime

import pytest

from harness.core.models import Run, RunStatus
from harness.sandbox.kubernetes import KubectlKubernetesClient, KubernetesSandboxProvider


@pytest.mark.asyncio
async def test_kubernetes_gvisor_live() -> None:
    if os.getenv("HARNESS_KUBERNETES_E2E") != "true":
        pytest.skip("set HARNESS_KUBERNETES_E2E=true for the cluster test")
    namespace = os.environ["HARNESS_KUBERNETES_NAMESPACE"]
    now = datetime.now(UTC)
    provider = KubernetesSandboxProvider(
        client=KubectlKubernetesClient(namespace=namespace),
        namespace=namespace,
        image=os.environ["HARNESS_KUBERNETES_IMAGE"],
        runtime_class_name=os.getenv("HARNESS_KUBERNETES_RUNTIME_CLASS_NAME", "gvisor"),
        egress_gateway_namespace=os.getenv(
            "HARNESS_KUBERNETES_EGRESS_GATEWAY_NAMESPACE", "harness-system"
        ),
        egress_gateway_selector={
            "app.kubernetes.io/name": "harness-egress-proxy"
        },
        egress_proxy_url=os.environ["HARNESS_KUBERNETES_EGRESS_PROXY_URL"],
    )
    handle = await provider.provision(
        Run(
            run_id="gvisor-live",
            session_id="gvisor-live",
            tenant_id="e2e",
            status=RunStatus.PROVISIONING,
            idempotency_key="gvisor-live",
            created_at=now,
            updated_at=now,
        )
    )
    try:
        await provider.prepare(handle)
        result = await provider.execute(handle, ("bash", "-lc", "printf gvisor-ready"))
        assert result.exit_code == 0
        assert result.stdout == "gvisor-ready"
        denied = await provider.execute(
            handle,
            (
                "node",
                "-e",
                "fetch('https://1.1.1.1').then(r=>process.exit(r.ok?9:0))"
                ".catch(()=>process.exit(0))",
            ),
        )
        assert denied.exit_code == 0
    finally:
        await provider.destroy(handle)
