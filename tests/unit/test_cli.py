from pathlib import Path

from pytest import CaptureFixture

from harness.cli import main
from harness.core.manifest import load_manifest


def test_agent_init_creates_a_valid_domain_agent_skeleton(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    root = tmp_path / "agents"

    exit_code = main(["agent", "init", "invoice-reviewer", "--root", str(root)])

    target = root / "invoice-reviewer"
    assert exit_code == 0
    assert (target / "agent.yaml").is_file()
    assert (target / "prompts" / "system.md").is_file()
    assert (target / "README.md").is_file()
    snapshot = load_manifest(target / "agent.yaml")
    assert snapshot.manifest.metadata.name == "invoice-reviewer"
    assert snapshot.manifest.metadata.version == "0.1.0"
    assert snapshot.manifest.spec.tools[0].builtin == "Read"
    assert "Initialized invoice-reviewer@0.1.0" in capsys.readouterr().out


def test_agent_init_never_overwrites_an_existing_directory(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    root = tmp_path / "agents"
    target = root / "invoice-reviewer"
    target.mkdir(parents=True)
    sentinel = target / "keep.txt"
    sentinel.write_text("user-owned")

    exit_code = main(["agent", "init", "invoice-reviewer", "--root", str(root)])

    assert exit_code == 2
    assert sentinel.read_text() == "user-owned"
    assert "already exists" in capsys.readouterr().err


def test_agent_init_rejects_invalid_names_before_creating_files(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    root = tmp_path / "agents"

    exit_code = main(["agent", "init", "Invoice Reviewer", "--root", str(root)])

    assert exit_code == 2
    assert not root.exists()
    assert "lowercase kebab-case" in capsys.readouterr().err


def test_agent_validate_prints_identity_and_content_hash(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    root = tmp_path / "agents"
    assert main(["agent", "init", "invoice-reviewer", "--root", str(root)]) == 0
    capsys.readouterr()

    exit_code = main(
        ["agent", "validate", str(root / "invoice-reviewer" / "agent.yaml")]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Valid invoice-reviewer@0.1.0" in output
    assert "sha256:" in output


def test_agent_validate_returns_a_stable_error_without_traceback(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    manifest = tmp_path / "agent.yaml"
    manifest.write_text("kind: not-an-agent\n")

    exit_code = main(["agent", "validate", str(manifest)])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert captured.err.startswith("error: ")
    assert "Traceback" not in captured.err

