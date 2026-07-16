"""Check every versioned Agent package and optionally build release bundles."""

from __future__ import annotations

import argparse
from pathlib import Path

from harness.agent_package import AgentPackageReport, check_agent_package, pack_agent_package


def check_catalog(
    root: Path,
    *,
    output_directory: Path | None = None,
) -> tuple[AgentPackageReport, ...]:
    manifests = sorted(root.glob("*/agent.yaml"))
    if not manifests:
        raise ValueError(f"no Agent packages found under {root}")
    reports: list[AgentPackageReport] = []
    identities: set[tuple[str, str]] = set()
    for manifest in manifests:
        report = check_agent_package(manifest, environment="production")
        metadata = report.snapshot.manifest.metadata
        identity = (metadata.name, metadata.version)
        if identity in identities:
            raise ValueError(
                f"duplicate Agent release identity: {metadata.name}@{metadata.version}"
            )
        identities.add(identity)
        reports.append(report)
        if output_directory is not None:
            pack_agent_package(manifest, output_directory=output_directory)
    return tuple(reports)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("agents"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    reports = check_catalog(args.root, output_directory=args.output)
    for report in reports:
        metadata = report.snapshot.manifest.metadata
        print(
            f"READY {metadata.name}@{metadata.version} "
            f"runtime-sha256:{report.snapshot.content_hash} "
            f"package-sha256:{report.package_hash} "
            f"evals:{len(report.eval_suite.cases)}"
        )


if __name__ == "__main__":
    main()
