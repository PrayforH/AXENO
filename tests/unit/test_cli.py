from pathlib import Path

import pytest
from pytest import CaptureFixture, MonkeyPatch

import harness.cli as cli
from harness.cli import main
from harness.core.manifest import load_manifest
from harness.evals.runner import EvalCaseResult, EvalReport


class RecordingPublisher:
    def __init__(self) -> None:
        self.manifests: list[Path] = []

    async def publish_agent(self, manifest_path: str) -> None:
        self.manifests.append(Path(manifest_path))


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
    assert (target / "skills" / "invoice-reviewer-core" / "SKILL.md").is_file()
    assert (target / "evals" / "suite.yaml").is_file()
    assert (target / "tools" / "README.md").is_file()
    assert (target / "README.md").is_file()
    snapshot = load_manifest(target / "agent.yaml")
    assert snapshot.manifest.metadata.name == "invoice-reviewer"
    assert snapshot.manifest.metadata.version == "0.1.0"
    assert snapshot.manifest.spec.tools[0].builtin == "Read"
    assert snapshot.skill_snapshots[0].name == "invoice-reviewer-core"
    assert "Initialized invoice-reviewer@0.1.0" in capsys.readouterr().out


def test_agent_init_operator_profile_sets_domain_and_reviewed_tools(
    tmp_path: Path,
) -> None:
    root = tmp_path / "agents"

    exit_code = main(
        [
            "agent",
            "init",
            "invoice-reviewer",
            "--root",
            str(root),
            "--template",
            "operator",
            "--domain",
            "accounts-payable",
        ]
    )

    snapshot = load_manifest(root / "invoice-reviewer" / "agent.yaml")
    tools = {tool.builtin for tool in snapshot.manifest.spec.tools}
    assert exit_code == 0
    assert snapshot.manifest.metadata.labels["domain"] == "accounts-payable"
    assert {"Read", "Write", "Edit", "Bash"}.issubset(tools)
    assert snapshot.manifest.spec.permissions.policy == "production-standard"


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


def test_agent_check_accepts_a_customized_production_scaffold(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    root = tmp_path / "agents"
    assert (
        main(
            [
                "agent",
                "init",
                "invoice-reviewer",
                "--root",
                str(root),
                "--domain",
                "accounts-payable",
            ]
        )
        == 0
    )
    capsys.readouterr()

    exit_code = main(
        [
            "agent",
            "check",
            str(root / "invoice-reviewer" / "agent.yaml"),
            "--environment",
            "production",
        ]
    )

    assert exit_code == 0
    assert "Production ready invoice-reviewer@0.1.0" in capsys.readouterr().out


def test_agent_pack_is_reproducible(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    root = tmp_path / "agents"
    assert (
        main(
            [
                "agent",
                "init",
                "invoice-reviewer",
                "--root",
                str(root),
                "--domain",
                "accounts-payable",
            ]
        )
        == 0
    )
    manifest = root / "invoice-reviewer" / "agent.yaml"
    capsys.readouterr()

    first_dir = tmp_path / "dist-one"
    second_dir = tmp_path / "dist-two"
    assert main(["agent", "pack", str(manifest), "--output", str(first_dir)]) == 0
    capsys.readouterr()
    assert main(["agent", "pack", str(manifest), "--output", str(second_dir)]) == 0

    first = next(first_dir.glob("*.zip"))
    second = next(second_dir.glob("*.zip"))
    assert first.name == second.name
    assert first.read_bytes() == second.read_bytes()
    assert "Packed invoice-reviewer@0.1.0" in capsys.readouterr().out


def test_agent_eval_returns_nonzero_and_prints_case_failures(
    tmp_path: Path,
    capsys: CaptureFixture[str],
    monkeypatch: MonkeyPatch,
) -> None:
    async def fake_live_eval(*_args: object, **_kwargs: object) -> EvalReport:
        return EvalReport(
            agent="invoice-reviewer",
            agent_version="1.0.0",
            cases=(
                EvalCaseResult(
                    case_id="safety",
                    run_id="run-1",
                    status="failed",
                    duration_seconds=1,
                    passed=False,
                    failures=("expected an approval request",),
                    tools=("Bash",),
                    approval_requested=False,
                ),
            ),
        )

    monkeypatch.setattr(cli, "_run_live_eval", fake_live_eval)

    junit = tmp_path / "reports" / "eval.xml"
    exit_code = main(
        [
            "agent",
            "eval",
            str(tmp_path / "agent.yaml"),
            "--junit",
            str(junit),
        ]
    )

    assert exit_code == 1
    output = capsys.readouterr().out
    assert "Evaluation FAILED invoice-reviewer@1.0.0: 0/1 cases" in output
    assert "safety: expected an approval request" in output
    assert 'tests="1"' in junit.read_text()


@pytest.mark.asyncio
async def test_live_publish_orders_local_pinned_subagents_first() -> None:
    publisher = RecordingPublisher()

    await cli._publish_local_agent_graph(  # pyright: ignore[reportPrivateUsage]
        publisher, Path("agents/public-opinion-agent/agent.yaml")
    )

    assert [path.parent.name for path in publisher.manifests] == [
        "helper-agent",
        "public-opinion-agent",
    ]
