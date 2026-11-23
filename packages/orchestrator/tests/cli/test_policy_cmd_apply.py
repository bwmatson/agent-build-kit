"""`abk policy apply`: the diff before the write, the question, the backup, the exit codes, the
toolset as a separate decision, and which agent a runtime's command names."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import main
from agent_build_kit.runtimes import policy_apply
from agent_build_kit.runtimes.known_agents import KNOWN_AGENTS
from agent_build_kit.runtimes.policy_apply import ApplyRefused
from agent_build_kit.runtimes.recommended_policy import patterns
from tests.cli.policy_apply_fakes import (
    AGENT,
    BARE,
    CURRENT_TOOLSET,
    DESCRIPTOR,
    NEUTRAL,
    OWN,
    Home,
    installation,
    run_apply,
    with_neutral_row,
)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Home:
    """A scratch agent home whose configuration holds three entries of the person's own."""
    scratch = Home(tmp_path, monkeypatch)
    scratch.holds(OWN, CURRENT_TOOLSET)
    return scratch


@pytest.fixture
def config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An installation whose runtime starts the known agent that has an applier."""
    path, _ = installation(tmp_path, monkeypatch, command=list(AGENT.variants[0].argv))
    return path


def text_of(terminal) -> str:
    return terminal.out + terminal.err


def test_the_diff_is_printed_before_the_question_and_a_yes_writes_and_reports(
    home: Home, config: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    before = home.config.read_text()

    code, terminal = run_apply(capsys, monkeypatch, config, home, answers=("y",))

    assert code == 0
    assert terminal.asked == 1
    assert str(home.config) in terminal.shown[0]
    assert "+++" in terminal.shown[0]
    assert patterns()[0] in terminal.shown[0]
    # at the question the file and the home are as the person left them
    assert terminal.texts == [before]
    assert terminal.homes == [[home.config.name]]
    assert home.deny() == [*OWN, *patterns()]
    assert str(home.backup) in terminal.out
    assert str(len(patterns())) in terminal.out
    assert home.backup.read_text() == before


def test_a_no_writes_nothing_and_exits_one(
    home: Home, config: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    before = home.config.read_text()

    code, terminal = run_apply(capsys, monkeypatch, config, home, answers=("n",))

    assert code == 1
    assert terminal.asked == 1
    assert home.config.read_text() == before
    assert home.files() == [home.config.name]


def test_an_empty_answer_is_a_no(
    home: Home, config: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _ = run_apply(capsys, monkeypatch, config, home, answers=("",))

    assert code == 1
    assert home.files() == [home.config.name]


def test_yes_takes_the_place_of_the_answer(
    home: Home, config: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, terminal = run_apply(capsys, monkeypatch, config, home, "--yes")

    assert code == 0
    assert terminal.asked == 0
    assert "+++" in terminal.out
    assert home.deny() == [*OWN, *patterns()]
    assert home.backup.exists()


def test_a_dry_run_prints_the_diff_and_writes_nothing(
    home: Home, config: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    before = home.config.read_text()

    code, terminal = run_apply(capsys, monkeypatch, config, home, "--dry-run")

    assert code == 0
    assert terminal.asked == 0
    assert "+++" in terminal.out
    assert patterns()[0] in terminal.out
    assert home.config.read_text() == before
    assert home.files() == [home.config.name]


def test_nothing_to_change_asks_nothing_and_exits_zero(
    home: Home, config: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home.holds([*OWN, *patterns()], CURRENT_TOOLSET)

    code, terminal = run_apply(capsys, monkeypatch, config, home)

    assert code == 0
    assert terminal.asked == 0
    assert "nothing changed" in terminal.out or "up to date" in terminal.out
    assert home.files() == [home.config.name]


def test_a_dry_run_with_yes_is_a_usage_problem(
    home: Home, config: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    before = home.config.read_text()

    code, terminal = run_apply(capsys, monkeypatch, config, home, "--dry-run", "--yes")

    assert code == 2
    assert "--dry-run" in text_of(terminal)
    assert home.config.read_text() == before
    assert home.files() == [home.config.name]


def test_an_agent_with_no_applier_exits_two_printing_the_patterns_command(
    home: Home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path, _ = installation(tmp_path, monkeypatch, command=list(BARE.variants[0].argv))
    before = home.config.read_text()

    code, terminal = run_apply(capsys, monkeypatch, path, home, "--yes")

    assert code == 2
    assert "abk policy patterns" in text_of(terminal)
    assert home.config.read_text() == before
    assert home.files() == [home.config.name]


def test_an_absent_configuration_exits_two_naming_the_file_and_writes_nothing(
    tmp_path: Path,
    config: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    empty = Home(tmp_path, monkeypatch)

    code, terminal = run_apply(capsys, monkeypatch, config, empty, "--yes")

    assert code == 2
    assert str(empty.config) in text_of(terminal)
    assert empty.files() == []


def test_a_configuration_that_does_not_parse_exits_two_naming_the_file(
    home: Home, config: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    broken = "approvals: [unclosed\n  deny: -\n"
    home.write(broken)

    code, terminal = run_apply(capsys, monkeypatch, config, home, "--yes")

    assert code == 2
    assert home.config.name in text_of(terminal)
    assert home.config.read_text() == broken
    assert home.files() == [home.config.name]


def test_a_wrong_shaped_list_exits_two_naming_the_file_and_the_key(
    home: Home, config: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    wrong = "approvals:\n  deny: {mine: 1}\n"
    home.write(wrong)

    code, terminal = run_apply(capsys, monkeypatch, config, home, "--yes")

    assert code == 2
    shown = text_of(terminal)
    assert home.config.name in shown
    assert ".".join(DESCRIPTOR.deny_path) in shown
    assert home.config.read_text() == wrong
    assert home.files() == [home.config.name]


def test_a_runtime_that_enforces_in_itself_has_nothing_to_apply(
    home: Home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path, _ = installation(tmp_path, monkeypatch, command=None)
    before = home.config.read_text()

    code, terminal = run_apply(capsys, monkeypatch, path, home, "--yes")

    assert code == 0
    assert "nothing to apply" in text_of(terminal).lower()
    assert home.config.read_text() == before
    assert home.files() == [home.config.name]


def test_after_a_write_the_check_is_named_and_no_agent_is_started(
    home: Home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path, runtime = installation(tmp_path, monkeypatch, command=list(AGENT.variants[0].argv))
    monkeypatch.setattr("subprocess.Popen", lambda *a, **k: pytest.fail("a program was started"))
    monkeypatch.setattr("subprocess.run", lambda *a, **k: pytest.fail("a program was run"))

    code, terminal = run_apply(capsys, monkeypatch, path, home, "--yes")

    assert code == 0
    assert "abk policy check" in terminal.out
    assert "spends no" in terminal.out
    assert runtime.checked == []


def test_the_toolset_is_shown_from_the_current_list_to_the_recommended_and_written_on_a_yes(
    home: Home, config: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert DESCRIPTOR.toolset is not None
    recommended = list(DESCRIPTOR.toolset.names)

    code, terminal = run_apply(capsys, monkeypatch, config, home, "--toolset", answers=("y",))

    assert code == 0
    # the question comes after the person has seen the list change
    for name in (*CURRENT_TOOLSET, *recommended):
        assert name in terminal.shown[0]
    assert home.toolset() == recommended
    assert home.deny() == [*OWN, *patterns()]


def test_without_the_flag_the_toolset_is_left_and_the_recommendation_stated(
    home: Home, config: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert DESCRIPTOR.toolset is not None

    code, terminal = run_apply(capsys, monkeypatch, config, home, "--yes")

    assert code == 0
    assert home.toolset() == CURRENT_TOOLSET
    assert "--toolset" in terminal.out
    for name in (*CURRENT_TOOLSET, *DESCRIPTOR.toolset.names):
        assert name in terminal.out


def test_the_flag_on_a_row_with_no_toolset_exits_two_saying_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with_neutral_row(monkeypatch)
    assert NEUTRAL.apply is not None
    scratch = Home(tmp_path, monkeypatch, NEUTRAL.apply)
    scratch.holds(OWN)
    path, _ = installation(tmp_path, monkeypatch, command=list(NEUTRAL.variants[0].argv))
    before = scratch.config.read_text()

    code, terminal = run_apply(capsys, monkeypatch, path, scratch, "--toolset", "--yes")

    assert code == 2
    assert "toolset" in text_of(terminal)
    assert scratch.config.read_text() == before
    assert scratch.files() == [scratch.config.name]


def test_a_second_row_is_applied_through_the_same_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with_neutral_row(monkeypatch)
    assert NEUTRAL.apply is not None
    scratch = Home(tmp_path, monkeypatch, NEUTRAL.apply)
    scratch.holds(OWN)
    path, _ = installation(tmp_path, monkeypatch, command=list(NEUTRAL.variants[0].argv))

    code, terminal = run_apply(capsys, monkeypatch, path, scratch, "--yes")

    assert code == 0, terminal.err
    assert scratch.deny() == [*OWN, *patterns()]


def test_agent_names_the_row_when_the_command_is_a_wrapper_the_table_does_not_recognise(
    home: Home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path, _ = installation(tmp_path, monkeypatch, command=["./run-agent.sh", "--serve"])

    unnamed, _ = run_apply(capsys, monkeypatch, path, home, "--yes")
    assert unnamed == 2
    assert home.files() == [home.config.name]

    code, _ = run_apply(capsys, monkeypatch, path, home, "--agent", AGENT.name, "--yes")

    assert code == 0
    assert home.deny() == [*OWN, *patterns()]


def test_an_unknown_agent_name_exits_two_naming_the_known_rows(
    home: Home, config: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    before = home.config.read_text()

    code, terminal = run_apply(
        capsys, monkeypatch, config, home, "--agent", "no such agent", "--yes"
    )

    assert code == 2
    shown = text_of(terminal)
    assert "no such agent" in shown
    for agent in KNOWN_AGENTS:
        assert agent.name in shown
    assert home.config.read_text() == before


def test_a_runtime_with_no_installation_to_read_it_from_exits_two_and_writes_nothing(
    home: Home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("ABK_CONFIG", raising=False)
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.chdir(empty)
    before = home.config.read_text()

    code = main(["policy", "apply", "--runtime", "acp", "--yes"])

    assert code == 2
    assert "--agent" in capsys.readouterr().err
    assert home.config.read_text() == before
    assert home.files() == [home.config.name]


def test_a_runtime_that_does_not_exist_exits_two_naming_the_runtimes_there_are(
    home: Home, config: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    before = home.config.read_text()

    code, terminal = run_apply(capsys, monkeypatch, config, home, "--runtime", "nosuch", "--yes")

    assert code == 2
    assert "nosuch" in terminal.err
    assert "fake" in terminal.err
    assert home.config.read_text() == before


def test_a_write_the_engine_refuses_after_the_question_is_a_refusal_not_a_traceback(
    home: Home, config: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    real = policy_apply.apply
    calls: list[bool] = []

    def refusing_write(*args: object, **kwargs: object) -> object:
        if not kwargs.get("dry_run"):
            calls.append(True)
            raise ApplyRefused("the file changed while you were asked")
        return real(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(policy_apply, "apply", refusing_write)

    code, terminal = run_apply(capsys, monkeypatch, config, home, answers=("y",))

    assert code == 2
    assert calls
    assert "the file changed while you were asked" in terminal.err


def test_the_installations_extras_are_applied_after_the_kits(
    home: Home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    extra = ["git * push --mirror*"]
    path, _ = installation(tmp_path, monkeypatch, command=list(AGENT.variants[0].argv), extra=extra)

    code, _ = run_apply(capsys, monkeypatch, path, home, "--yes")

    assert code == 0
    assert home.deny() == [*OWN, *patterns(), *extra]
