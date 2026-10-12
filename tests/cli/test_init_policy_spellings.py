"""`abk init` prints the unrefused spelling the way `abk doctor` does, and asks before the fix."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent_build_kit.cli import init as init_cmd
from agent_build_kit.cli import main
from tests.cli.test_init import app, init_args, loosened, stubs  # noqa: F401 — fixtures
from tests.factories import recognised_planning
from tests.runtimes.selectable import amend_finding, spelling_report


def test_an_unrefused_spelling_is_printed_by_class_and_spelling_and_the_fix_asked_first(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime = loosened(tmp_path, app, monkeypatch, spelling_report())
    planning = recognised_planning(tmp_path / "planning")
    capsys.readouterr()
    asked: list[str] = []

    def ask(prompt: str) -> str:
        asked.append(capsys.readouterr().out)
        runtime.log.append("ask")
        return "y"

    def run_fix(argv, **kwargs):
        runtime.log.append("fix")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(init_cmd, "ask", ask)
    monkeypatch.setattr(init_cmd, "run_fix", run_fix)

    main(init_args(planning, app))

    # What was printed when the operator was asked: the open class alone, its
    # open spelling and the class's other spellings as refused.
    assert len(asked) == 1
    assert f"runtime loose does not refuse: {amend_finding()}\n" in asked[0]
    assert "merging a pull request" not in asked[0]
    assert runtime.log == ["check", "ask", "fix", "check"]
