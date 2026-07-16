"""Pack every Agent twice and reject nondeterministic release archives."""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

from harness.agent_package import pack_agent_package


def _hashes(directory: Path) -> dict[str, str]:
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.glob("*.zip"))
    }


def _pack_catalog(root: Path, output: Path) -> None:
    manifests = sorted(root.glob("*/agent.yaml"))
    if not manifests:
        raise ValueError(f"no Agent packages found under {root}")
    identities: set[tuple[str, str]] = set()
    for manifest in manifests:
        _archive, report = pack_agent_package(manifest, output_directory=output)
        metadata = report.snapshot.manifest.metadata
        identity = (metadata.name, metadata.version)
        if identity in identities:
            raise ValueError(
                f"duplicate Agent release identity: {metadata.name}@{metadata.version}"
            )
        identities.add(identity)


def verify(root: Path) -> dict[str, str]:
    with tempfile.TemporaryDirectory(prefix="harness-pack-a-") as first_directory:
        with tempfile.TemporaryDirectory(prefix="harness-pack-b-") as second_directory:
            first = Path(first_directory)
            second = Path(second_directory)
            _pack_catalog(root, first)
            _pack_catalog(root, second)
            first_hashes = _hashes(first)
            second_hashes = _hashes(second)
    if not first_hashes or first_hashes != second_hashes:
        raise ValueError("Agent bundle output is not byte-for-byte deterministic")
    return first_hashes


def main() -> None:
    for name, digest in verify(Path("agents")).items():
        print(f"DETERMINISTIC {name} sha256:{digest}")


if __name__ == "__main__":
    main()
