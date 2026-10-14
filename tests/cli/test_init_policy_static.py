"""`abk init`'s policy step reads the agent's configuration: it asks no token question, prints
each class with its refusing pattern, exits by the rule, and checks again after a fix by
reading the file again."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import init as init_cmd
from agent_build_kit.cli import main
from agent_build_kit.runtimes.acp import PROBE_CLASSES
from agent_build_kit.runtimes.recommended_policy import matches, patterns
from tests.cli.policy_static_cli import UNKNOWN_PROGRAM, agent_command, planning_for
from tests.cli.policy_step_fakes import real_fixes, script
from tests.cli.test_init import app, stubs  # noqa: F401 — fixtures
from tests.runtimes.policy_static_support import (
    UNCOVERED_LABELS,
    agent_home,
    config_file,
    write_config,
)

CANNOT = "cannot check: abk has no policy for this agent"


def forbid_questions(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(prompt: str) -> str:
        pytest.fail(f"a question was asked: {prompt!r}")

    monkeypatch.setattr(init_cmd, "ask", refuse)


@pytest.mark.parametrize("flags", [(), ("--yes",)])
def test_no_token_question_is_asked_and_each_class_is_printed_with_its_pattern(
    flags: tuple[str, ...],
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    deny = patterns()
    write_config(agent_home(tmp_path, monkeypatch), deny)
    planning = planning_for(tmp_path, app, monkeypatch, agent_command())
    forbid_questions(monkeypatch)
    capfd.readouterr()

    code = main(["init", str(planning), "--policy-only", *flags])

    shown = capfd.readouterr()
    text = shown.out + shown.err
    assert code == 0
    assert "spends tokens" not in text
    for command, label in PROBE_CLASSES:
        if label in UNCOVERED_LABELS:
            continue
        first = next(p for p in deny if matches(p, command))
        assert label in text
        assert first in text


def test_a_class_not_refused_exits_one(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    write_config(agent_home(tmp_path, monkeypatch), [p for p in patterns() if "amend" not in p])
    planning = planning_for(tmp_path, app, monkeypatch, agent_command())
    forbid_questions(monkeypatch)
    capfd.readouterr()

    code = main(["init", str(planning), "--policy-only", "--yes"])

    assert code == 1
    assert "amending a commit" in capfd.readouterr().out


def test_a_check_that_cannot_be_made_exits_one_saying_so(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    write_config(agent_home(tmp_path, monkeypatch), patterns())
    planning = planning_for(tmp_path, app, monkeypatch, agent_command(UNKNOWN_PROGRAM))
    forbid_questions(monkeypatch)
    capfd.readouterr()

    code = main(["init", str(planning), "--policy-only", "--yes"])

    shown = capfd.readouterr()
    assert code == 1
    assert CANNOT in shown.out + shown.err


def test_a_run_policy_fix_is_followed_by_a_check_that_reads_the_file_again(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    home = agent_home(tmp_path, monkeypatch)
    good = tmp_path / "good.yaml"
    write_config(home, patterns())
    good.write_text(config_file(home).read_text())
    write_config(home, [])
    fix = script(tmp_path / "fix.sh", f'cp "{good}" "{config_file(home)}"\n')
    planning = planning_for(tmp_path, app, monkeypatch, agent_command(), policy_fix=fix)
    forbid_questions(monkeypatch)
    real_fixes(monkeypatch)
    capfd.readouterr()

    code = main(["init", str(planning), "--policy-only", "--yes", "--run-policy-fix"])

    assert code == 0
    assert "now refuses every forbidden class" in capfd.readouterr().out


def test_the_built_in_fix_is_followed_by_a_check_that_reads_the_file_again(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    home = agent_home(tmp_path, monkeypatch)
    write_config(home, ["mine *"])
    planning = planning_for(tmp_path, app, monkeypatch, agent_command())
    forbid_questions(monkeypatch)
    capfd.readouterr()

    code = main(["init", str(planning), "--policy-only", "--yes", "--run-policy-fix"])

    assert code == 0
    assert "now refuses every forbidden class" in capfd.readouterr().out
    assert patterns()[0] in config_file(home).read_text()
