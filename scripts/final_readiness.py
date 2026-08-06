"""Print the reproducible final repository-readiness audit as JSON."""

from __future__ import annotations

import json
from pathlib import Path

from harness.readiness import audit_repository


def main() -> None:
    audit = audit_repository(Path.cwd())
    print(
        json.dumps(
            audit.model_dump(mode="json", by_alias=True),
            sort_keys=True,
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
