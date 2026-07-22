import pytest

from harness.policy.bash_safety import sandboxed_bash_is_low_risk


@pytest.mark.parametrize(
    "command",
    [
        "pwd && ls -la",
        "wc -l outputs/report.html outputs/items.csv && head -5 outputs/items.csv | cut -c1-120",
        "grep -n report outputs/report.html | head -20",
        "rg --count html /workspace/outputs/report.html",
        "/usr/bin/stat outputs/report.html",
        "sha256sum outputs/report.html",
        'find / -name "generated_grid.jpg" 2>/dev/null',
        "ls -la /home/user/ 2>/dev/null; ls -la / 2>/dev/null",
        'ls -la inputs/ && echo "---" && ls -la .claude/ && echo "---" && ls -la .harness-runtime/',
        "tail -20 outputs/report.html",
        (
            'ls .claude/skills/grid-system/scripts/ 2>/dev/null || '
            'find . -name "add_grid.py" 2>/dev/null'
        ),
        (
            "mkdir -p outputs/detection_output outputs/results && "
            "python .claude/skills/grid-system/scripts/add_grid.py inputs/sample.jpg"
        ),
        (
            "cp /tmp/detection_output/sample_annotated.jpg outputs/detection_output/ && "
            "cp /tmp/detection_output/sample_grid.jpg outputs/detection_output/"
        ),
        "python3 .harness-runtime/bundle-tools/abc/tools/filter.py outputs/result.json",
        (
            "python - <<'PY'\n"
            "from pathlib import Path\n"
            "for p in sorted(Path('outputs').rglob('*')):\n"
            "    if p.is_file():\n"
            "        print(f'{p} {p.stat().st_size} bytes')\n"
            "PY"
        ),
        (
            "cat > outputs/detection.json << 'EOF'\n"
            '{"detected": true, "target_count": 2}\n'
            "EOF\n"
            "cat outputs/detection.json"
        ),
    ],
)
def test_allows_low_risk_read_only_commands(command: str) -> None:
    assert sandboxed_bash_is_low_risk(command, workspace="/workspace") is True


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf outputs",
        "curl https://example.test",
        "python scripts/validate.py",
        "python -c 'print(1)'",
        "mkdir /tmp/outside-workspace",
        "cp /etc/passwd outputs/passwd",
        "cp /tmp/detection_output/sample.jpg /tmp/outside-workspace",
        "cp -R /tmp/detection_output outputs/",
        "cat /etc/passwd",
        "env",
        "echo $HARNESS_NEW_API_KEY",
        "wc -l outputs/report.html > outputs/count.txt",
        "find outputs -type f -delete",
        "find outputs -type f -exec sh -c 'echo unsafe' \\;",
        "wc -l $(find outputs -type f)",
        "ls ../another-run",
        "rg --pre 'sh formatter.sh' pattern outputs/report.html",
        "./wc outputs/report.html",
        "python - <<PY\nprint('shell expansion is not isolated')\nPY",
        "python - <<'PY'\nfrom pathlib import Path\nPath('outputs/result.txt').write_text('x')\nPY",
        "python - <<'PY'\nimport os\nprint(os.environ)\nPY",
        "python - <<'PY'\nfrom pathlib import Path\nprint(Path('/etc/passwd').read_text())\nPY",
        "python - <<'PY'\nwhile True:\n    pass\nPY",
        "cat > inputs/source.json << 'EOF'\n{}\nEOF",
        "cat > /tmp/outside.json << 'EOF'\n{}\nEOF",
        "cat > outputs/result.json << EOF\n$HARNESS_NEW_API_KEY\nEOF",
    ],
)
def test_rejects_commands_that_are_not_provably_low_risk(command: str) -> None:
    assert sandboxed_bash_is_low_risk(command, workspace="/workspace") is False


def test_allows_current_remote_workspace_but_not_other_absolute_paths() -> None:
    assert sandboxed_bash_is_low_risk(
        "wc -l /home/user/run/outputs/report.html",
        workspace="/tmp/local-run",
        remote_workspace="/home/user/run",
    )
    assert not sandboxed_bash_is_low_risk(
        "wc -l /home/user/another-run/outputs/report.html",
        workspace="/tmp/local-run",
        remote_workspace="/home/user/run",
    )
