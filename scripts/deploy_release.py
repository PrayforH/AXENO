"""Apply or roll back digest-pinned Compose releases on a deployment runner."""

from __future__ import annotations

import argparse
from pathlib import Path

from harness.release import load_release_manifest, verify_release_manifest
from harness.release_deploy import ReleaseComposeDeployer


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("apply", "rollback"))
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--compose-env", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--environment", choices=("test", "canary", "production"), required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--artifact-root", type=Path)
    args = parser.parse_args()
    deployer = ReleaseComposeDeployer(
        repository_root=args.repository_root,
        compose_env_file=args.compose_env,
        state_root=args.state_root,
        environment_name=args.environment,
    )
    if args.command == "rollback":
        manifest = deployer.rollback()
        print(f"ROLLED_BACK release-sha256:{manifest.release_id}")
        return
    if args.manifest is None or args.artifact_root is None:
        parser.error("apply requires --manifest and --artifact-root")
    manifest = load_release_manifest(args.manifest)
    verify_release_manifest(manifest, artifact_root=args.artifact_root)
    applied = deployer.apply(args.manifest)
    print(f"DEPLOYED release-sha256:{applied.release_id}")


if __name__ == "__main__":
    main()
