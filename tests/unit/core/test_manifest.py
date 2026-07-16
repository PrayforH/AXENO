from pathlib import Path

import pytest

from harness.core.manifest import ManifestValidationError, load_manifest

FIXTURE = Path("tests/fixtures/agents/echo-agent/agent.yaml")
VALIDATION_AGENT = Path("agents/echo-agent/agent.yaml")
HELPER_AGENT = Path("agents/helper-agent/agent.yaml")


def test_loads_valid_manifest_and_resolves_prompt() -> None:
    snapshot = load_manifest(FIXTURE)

    assert snapshot.manifest.metadata.name == "echo-agent"
    assert snapshot.manifest.metadata.version == "0.1.0"
    assert snapshot.system_prompt.startswith("You are a deterministic echo agent")
    assert len(snapshot.content_hash) == 64


def test_content_hash_is_deterministic() -> None:
    assert load_manifest(FIXTURE).content_hash == load_manifest(FIXTURE).content_hash


def test_validation_agent_exposes_workspace_tools_with_safe_prompt() -> None:
    snapshot = load_manifest(VALIDATION_AGENT)

    assert snapshot.manifest.metadata.version == "0.4.0"
    assert tuple(tool.builtin for tool in snapshot.manifest.spec.tools) == (
        "Read",
        "Glob",
        "Grep",
        "Write",
        "Edit",
        "Bash",
        "Task",
    )
    assert all(tool.mcp is None for tool in snapshot.manifest.spec.tools)
    assert tuple(item.ref for item in snapshot.manifest.spec.subagents) == (
        "helper-agent@1.0.0",
    )
    assert "only when the user requests" in snapshot.system_prompt.lower()
    assert "run workspace" in snapshot.system_prompt.lower()
    assert "untrusted" in snapshot.system_prompt.lower()
    assert "echo the user's request" not in snapshot.system_prompt.lower()


def test_validation_helper_agent_is_bounded_to_read_only_investigation() -> None:
    snapshot = load_manifest(HELPER_AGENT)

    assert snapshot.manifest.metadata.name == "helper-agent"
    assert snapshot.manifest.metadata.version == "1.0.0"
    assert tuple(tool.builtin for tool in snapshot.manifest.spec.tools) == (
        "Read",
        "Glob",
        "Grep",
    )
    assert snapshot.manifest.spec.subagents == ()
    assert "parent agent" in snapshot.system_prompt.lower()


def test_rejects_unknown_runtime(tmp_path: Path) -> None:
    manifest = (FIXTURE.read_text()).replace("claude-agent-sdk", "unknown-runtime")
    path = tmp_path / "agent.yaml"
    path.write_text(manifest)
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts/system.md").write_text("prompt")

    with pytest.raises(ManifestValidationError, match="runtime"):
        load_manifest(path)


def test_rejects_latest_subagent_in_production(tmp_path: Path) -> None:
    manifest = FIXTURE.read_text().replace("helper@1.0.0", "helper@latest")
    path = tmp_path / "agent.yaml"
    path.write_text(manifest)
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts/system.md").write_text("prompt")

    with pytest.raises(ManifestValidationError, match="latest"):
        load_manifest(path, environment="production")


def test_rejects_missing_prompt(tmp_path: Path) -> None:
    path = tmp_path / "agent.yaml"
    path.write_text(FIXTURE.read_text())

    with pytest.raises(ManifestValidationError, match="system prompt"):
        load_manifest(path)


def test_rejects_inline_secrets(tmp_path: Path) -> None:
    manifest = FIXTURE.read_text() + "\n  apiKey: sk-should-not-be-here\n"
    path = tmp_path / "agent.yaml"
    path.write_text(manifest)
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts/system.md").write_text("prompt")

    with pytest.raises(ManifestValidationError, match="secret-like field"):
        load_manifest(path)
