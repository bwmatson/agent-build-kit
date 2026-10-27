"""A track run's write grant follows the reports directory: `--planning-reports-dir` grants
`*.md` writes under it, an outside state directory is not granted, and the earlier
`--planning-state-dir` flag is read as the same."""

from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path

import pytest

from agent_build_kit.hooks.policy import main


def checkouts(tmp_path: Path) -> tuple[Path, Path]:
    code, planning = tmp_path / "code", tmp_path / "planning"
    for checkout in (code, planning):
        checkout.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=checkout, check=True)
    return code, planning


def answer(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    flags: list[str],
    target: Path,
    cwd: Path,
) -> str:
    """`allow` or `deny`: the hook's answer to a write of `target` run with these flags."""
    payload = {"tool_name": "Write", "cwd": str(cwd), "tool_input": {"file_path": str(target)}}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    assert main(flags) == 0
    out = capsys.readouterr().out
    return json.loads(out)["hookSpecificOutput"]["permissionDecision"] if out else "allow"


def test_the_reports_directory_is_granted_and_an_outside_state_directory_is_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, planning = checkouts(tmp_path)
    state = tmp_path / "state"
    state.mkdir()
    reports = planning / "docs" / "reports"
    flags = ["--planning-repo", str(planning), "--planning-reports-dir", str(reports)]

    def ask(target: Path) -> str:
        return answer(monkeypatch, capsys, flags, target, code)

    assert ask(reports / "x-app-health.md") == "allow"
    assert ask(reports / "x.json") == "deny"
    assert ask(state / "x.md") == "deny"
    assert ask(planning / "docs" / "other.md") == "deny"


def test_the_earlier_state_dir_flag_is_read_as_the_reports_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, planning = checkouts(tmp_path)
    reports = planning / "docs" / "reports"
    new = ["--planning-repo", str(planning), "--planning-reports-dir", str(reports)]
    old = ["--planning-repo", str(planning), "--planning-state-dir", str(reports)]
    target = reports / "x-app-health.md"

    assert answer(monkeypatch, capsys, new, target, code) == "allow"
    assert answer(monkeypatch, capsys, old, target, code) == "allow"
