"""Developer CLI for creating and validating domain Agent packages."""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from harness.core.manifest import ManifestValidationError, load_manifest

_AGENT_NAME = re.compile(r"^[a-z][a-z0-9-]*$")
_INITIAL_VERSION = "0.1.0"


class CliError(ValueError):
    """Expected command-line usage error."""


def _manifest_template(name: str) -> str:
    return f"""apiVersion: harness/v1alpha1
kind: Agent
metadata:
  name: {name}
  version: {_INITIAL_VERSION}
  labels:
    domain: replace-me
spec:
  runtime: claude-agent-sdk
  model:
    route: new-api-default
    model: claude-sonnet-4-6
    requiredCapabilities:
      - streaming
      - tool_use
  prompt:
    system: prompts/system.md
  skills: []
  tools:
    - builtin: Read
  subagents: []
  hooks: []
  permissions:
    policy: local-standard
  workspace:
    mode: isolated
    restoreSession: true
    archiveOnComplete: true
  limits:
    maxTurns: 12
    timeoutSeconds: 600
    maxBudgetUsd: 1
"""


def _prompt_template(name: str) -> str:
    return f"""# {name}

You are a domain agent running inside Claude Agent Harness.

## Mission

Describe the business outcome this agent owns.

## Operating workflow

1. Confirm the user's goal and required inputs.
2. Gather evidence with the minimum necessary tools.
3. State uncertainty and request approval before consequential actions.
4. Return a concise result with sources, decisions, and next actions.

## Boundaries

- Never invent business records or claim an action succeeded without tool evidence.
- Keep secrets and personal data out of responses, artifacts, and logs.
- Follow Harness permission decisions and stop when a required approval is denied.

## Output contract

Replace this section with the domain-specific response structure and quality bar.
"""


def _readme_template(name: str) -> str:
    return f"""# {name}

This directory is a versioned domain Agent package for Claude Agent Harness.

## Start here

1. Replace the mission, workflow, boundaries, and output contract in `prompts/system.md`.
2. Adjust model capabilities, builtin tools, limits, and the permission policy in `agent.yaml`.
3. Validate with `harness agent validate agents/{name}/agent.yaml`.
4. Publish the validated Manifest through the Harness Agent API before creating sessions.

Python tools use an installed `module:attribute` export containing Claude SDK
`SdkMcpTool` objects. External MCP entries are logical IDs configured in the
Harness server registry; never put commands, URLs, headers, or secrets here.
"""


def _init_agent(name: str, root: Path) -> None:
    if _AGENT_NAME.fullmatch(name) is None:
        raise CliError("agent name must be lowercase kebab-case")
    target = root / name
    if target.exists():
        raise CliError(f"target already exists: {target}")

    prompt_directory = target / "prompts"
    prompt_directory.mkdir(parents=True)
    (target / "agent.yaml").write_text(_manifest_template(name))
    (prompt_directory / "system.md").write_text(_prompt_template(name))
    (target / "README.md").write_text(_readme_template(name))

    snapshot = load_manifest(target / "agent.yaml")
    print(
        f"Initialized {snapshot.manifest.metadata.name}@"
        f"{snapshot.manifest.metadata.version} at {target}"
    )


def _validate_agent(path: Path) -> None:
    snapshot = load_manifest(path)
    print(
        f"Valid {snapshot.manifest.metadata.name}@{snapshot.manifest.metadata.version} "
        f"sha256:{snapshot.content_hash}"
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="harness")
    commands = parser.add_subparsers(dest="command", required=True)
    agent = commands.add_parser("agent", help="create and validate Agent packages")
    actions = agent.add_subparsers(dest="agent_action", required=True)

    initialize = actions.add_parser("init", help="create a domain Agent skeleton")
    initialize.add_argument("name")
    initialize.add_argument("--root", type=Path, default=Path("agents"))

    validate = actions.add_parser("validate", help="validate and hash an Agent Manifest")
    validate.add_argument("manifest", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        action = cast(str, args.agent_action)
        if action == "init":
            _init_agent(cast(str, args.name), cast(Path, args.root))
        else:
            _validate_agent(cast(Path, args.manifest))
    except (CliError, ManifestValidationError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


def entrypoint() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    entrypoint()

