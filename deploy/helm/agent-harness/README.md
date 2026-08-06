# Kubernetes/gVisor execution plane

The chart installs the least-privilege worker RBAC, a tokenless sandbox service
account, and an optional allowlisted HTTP CONNECT proxy. Install gVisor on the
cluster first; set `sandbox.createRuntimeClass=true` only when the `runsc` handler
already exists on every eligible node.

Build `deploy/docker/sandbox.Dockerfile`, push it by digest, then configure the
worker with `HARNESS_SANDBOX_PROVIDER=kubernetes`,
`HARNESS_KUBERNETES_IMAGE=<registry/image>@sha256:<digest>`, and
`HARNESS_KUBERNETES_EGRESS_PROXY_URL=http://harness-egress-proxy.harness-system.svc:3128`.

Each Run creates one Pod and one default-deny NetworkPolicy. The Pod can reach
only cluster DNS and the labeled proxy; Squid rejects destinations outside
`egressProxy.allowedDomains`. The Reaper deletes expired Pods and policies using
the immutable expiry annotation.
