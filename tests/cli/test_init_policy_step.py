"""`abk init`'s guided policy step: what it asks, what it prints before and after a fix, how
the fix runs, and what it never claims."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from agent_build_kit.cli import init as init_cmd
from agent_build_kit.cli import main
from agent_build_kit.runtimes.base import validate_argv
from tests.cli.policy_step_fakes import (
    AMEND_ROW,
    PUSH_ROW,
    Operator,
    PolicyFileRuntime,
    changing_nothing,
    command_of,
    configured,
    patching,
    policy_file,
    real_fixes,
    recorded,
)
from tests.cli.test_init import app, init_args, stubs  # noqa: F401 — fixtures
from tests.runtimes.selectable import AMEND
from tests.spelling_rows import PUSH


@pytest.fixture
def events() -> list[str]:
    return []


def test_a_known_agent_s_fix_is_offered_run_on_a_yes_and_checked_again(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    events: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    patched = policy_file(tmp_path / "policy.txt", AMEND_ROW)
    fix = [*patching(tmp_path, "patch.sh"), str(patched)]
    runtime = PolicyFileRuntime("known", patched, log=events)
    planning = configured(tmp_path, app, monkeypatch, runtime, policy_fix=fix)
    events.clear()
    operator = Operator(capfd, "y", log=events)
    monkeypatch.setattr(init_cmd, "ask", operator)
    real_fixes(monkeypatch)

    main(init_args(planning, app))

    assert events == ["check", "ask", "check"]
    assert patched.read_text() == ""
    # Told, per spelling, what the second check found.
    after = capfd.readouterr().out
    assert command_of(AMEND, AMEND_ROW[1]) in after
    assert "not refused" not in after


def test_a_fix_that_leaves_a_spelling_open_is_reported_as_still_unenforced(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    events: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    patched = policy_file(tmp_path / "policy.txt", AMEND_ROW, PUSH_ROW)
    fix = [*patching(tmp_path, "patch.sh"), str(patched)]
    runtime = PolicyFileRuntime("partial", patched, log=events)
    planning = configured(tmp_path, app, monkeypatch, runtime, policy_fix=fix)
    events.clear()
    monkeypatch.setattr(init_cmd, "ask", Operator(capfd, "y", log=events))
    real_fixes(monkeypatch)

    main(init_args(planning, app))

    after = capfd.readouterr().out
    assert events == ["check", "ask", "check"]
    assert "refuses every forbidden class" not in after
    assert "not refused" in after
    assert command_of(PUSH, PUSH_ROW[1]) in after.split("not refused")[-1]
    # The spelling the fix did close is reported too, not only what is left.
    assert command_of(AMEND, AMEND_ROW[1]) in after


def test_an_unknown_agent_is_offered_two_choices_and_none_is_guessed(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    events: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    runtime = PolicyFileRuntime(
        "unknown", policy_file(tmp_path / "policy.txt", AMEND_ROW), log=events
    )
    planning = configured(tmp_path, app, monkeypatch, runtime)
    before = (planning / "abk.yaml").read_text()
    events.clear()
    operator = Operator(capfd, "1", log=events)
    monkeypatch.setattr(init_cmd, "ask", operator)

    main(init_args(planning, app))

    menu = operator.screens[0].lower()
    assert "rely" in menu
    assert "continue without" not in menu
    assert "unchecked" not in menu
    assert "fix command" in menu
    # Relying on abk's own layer runs nothing and records nothing.
    assert events == ["check", "ask"]
    assert (planning / "abk.yaml").read_text() == before


def test_an_unknown_agent_s_fix_is_validated_recorded_run_and_checked_again(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    events: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    patched = policy_file(tmp_path / "policy.txt", AMEND_ROW)
    fix = patching(tmp_path, "patch.sh")
    runtime = PolicyFileRuntime("unknown", patched, log=events)
    planning = configured(tmp_path, app, monkeypatch, runtime)
    events.clear()
    missing = "no-such-program-here"
    operator = Operator(capfd, "2", missing, f"{fix[0]} {patched}", log=events)
    monkeypatch.setattr(init_cmd, "ask", operator)
    real_fixes(monkeypatch)

    main(init_args(planning, app))

    problem = validate_argv(missing, shutil.which)
    assert problem
    assert problem in operator.screens[2]
    assert recorded(planning, "unknown")["policy_fix"] == [*fix, str(patched)]
    assert patched.read_text() == ""
    assert events.count("check") == 2


def test_an_answer_of_three_is_not_a_choice_and_records_no_marker(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    events: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    runtime = PolicyFileRuntime(
        "unknown", policy_file(tmp_path / "policy.txt", AMEND_ROW), log=events
    )
    planning = configured(tmp_path, app, monkeypatch, runtime)
    monkeypatch.setattr(init_cmd, "ask", Operator(capfd, "3", otherwise="1"))

    main(init_args(planning, app))

    assert "policy" not in recorded(planning, "unknown")
    assert "policy_fix" not in recorded(planning, "unknown")


def test_the_fix_and_what_it_must_close_are_printed_before_it_runs_and_its_output_is_not_captured(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    events: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    patched = policy_file(tmp_path / "policy.txt", AMEND_ROW)
    fix = [*patching(tmp_path, "patch.sh"), str(patched)]
    runtime = PolicyFileRuntime("known", patched, log=events)
    planning = configured(tmp_path, app, monkeypatch, runtime, policy_fix=fix)
    operator = Operator(capfd, "y", log=events)
    monkeypatch.setattr(init_cmd, "ask", operator)
    real_fixes(monkeypatch)

    main(init_args(planning, app))

    asked = operator.screens[0]
    assert "patch.sh" in asked
    assert AMEND in asked
    assert command_of(AMEND, AMEND_ROW[1]) in asked
    assert "patching the agent policy" not in asked
    shown = capfd.readouterr()
    assert "patching the agent policy" in shown.out
    assert "a note on stderr" in shown.err
    assert "stdout was captured" not in shown.out


def test_a_fix_that_exits_non_zero_is_reported_with_its_status_and_checked_again(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    events: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    patched = policy_file(tmp_path / "policy.txt", AMEND_ROW, PUSH_ROW)
    fix = [*patching(tmp_path, "patch.sh", exits=3), str(patched)]
    runtime = PolicyFileRuntime("known", patched, log=events)
    planning = configured(tmp_path, app, monkeypatch, runtime, policy_fix=fix)
    events.clear()
    monkeypatch.setattr(init_cmd, "ask", Operator(capfd, "y", log=events))
    real_fixes(monkeypatch)

    main(init_args(planning, app))

    shown = capfd.readouterr()
    said = shown.out + shown.err
    assert "exit" in said and "3" in said
    assert "stdout was captured" not in said
    # A partial patch may have landed: the check ran again, and saw the one it closed.
    assert events == ["check", "ask", "check"]
    assert command_of(PUSH, PUSH_ROW[1]) in said.split("not refused")[-1]


def test_a_fix_that_changes_nothing_says_so_and_names_what_is_still_open(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    patched = policy_file(tmp_path / "policy.txt", AMEND_ROW)
    fix = [*changing_nothing(tmp_path), str(patched)]
    runtime = PolicyFileRuntime("known", patched, log=[])
    planning = configured(tmp_path, app, monkeypatch, runtime, policy_fix=fix)
    monkeypatch.setattr(init_cmd, "ask", Operator(capfd, "y"))
    real_fixes(monkeypatch)

    main(init_args(planning, app))

    said = capfd.readouterr().out
    open_command = command_of(AMEND, AMEND_ROW[1])
    assert "the fix made no change; still not refused: " in said
    assert open_command in said.split("the fix made no change; still not refused: ")[1]


def test_a_kept_abk_yaml_asks_no_runtime_question_and_applies_the_configured_fix(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    events: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    patched = policy_file(tmp_path / "policy.txt", AMEND_ROW)
    fix = [*patching(tmp_path, "patch.sh"), str(patched)]
    runtime = PolicyFileRuntime("known", patched, log=events)
    planning = configured(tmp_path, app, monkeypatch, runtime, policy_fix=fix)
    before = (planning / "abk.yaml").read_bytes()
    operator = Operator(capfd, "y", log=events)
    monkeypatch.setattr(init_cmd, "ask", operator)
    real_fixes(monkeypatch)

    main(init_args(planning, app))

    # The one question is whether to run the fix; the person's output is not captured.
    assert len(operator.screens) == 1
    assert "stdout was captured" not in capfd.readouterr().out
    assert patched.read_text() == ""
    assert (planning / "abk.yaml").read_bytes() == before


def test_an_answer_that_is_not_a_choice_is_asked_again_and_nothing_is_recorded(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    events: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    runtime = PolicyFileRuntime(
        "unknown", policy_file(tmp_path / "policy.txt", AMEND_ROW), log=events
    )
    planning = configured(tmp_path, app, monkeypatch, runtime)
    before = (planning / "abk.yaml").read_text()
    operator = Operator(capfd, "", "x", "1", log=events)
    monkeypatch.setattr(init_cmd, "ask", operator)

    main(init_args(planning, app))

    assert len(operator.screens) == 3
    assert "nothing is chosen" in operator.screens[1]
    assert (planning / "abk.yaml").read_text() == before
