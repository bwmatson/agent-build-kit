"""`abk init`'s policy step offering the kit's recommended policy as the fix: when it is offered,
what is shown before and after it is applied, what takes precedence over it, and what `--yes`
does and does not let it do."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent_build_kit.cli import init as init_cmd
from agent_build_kit.cli import main
from agent_build_kit.runtimes import PolicyReport
from agent_build_kit.runtimes.recommended_policy import patterns
from tests.cli.policy_apply_fakes import AGENT, BARE, CURRENT_TOOLSET, OWN, Home
from tests.cli.policy_step_fakes import (
    AMEND_ROW,
    PUSH_ROW,
    Operator,
    changing_nothing,
    command_of,
    configured,
    real_fixes,
    recorded,
)
from tests.cli.test_init import app, stubs  # noqa: F401 — fixtures
from tests.runtimes.selectable import AMEND, SelectableRuntime, spelling_report
from tests.spelling_rows import PUSH


class ConfigRuntime(SelectableRuntime):
    """A runtime whose check finds the amend and push classes unrefused until the agent's
    configuration holds every recommended pattern, then only the `stubborn` rows: what an
    agent's own matcher lets through whatever its list says."""

    def __init__(
        self, home: Home, *, stubborn: tuple = (), log: list[str], prompts: bool = False
    ) -> None:
        super().__init__("builtin", log=log)
        self.home = home
        self.stubborn = set(stubborn)
        self.policy_check_prompts_agent = prompts

    def check_policy(self, cwd: Path) -> PolicyReport:
        self.checked.append(cwd)
        self.log.append("check")
        applied = self.home.config.exists() and set(patterns()) <= set(self.home.deny())
        return spelling_report(open_rows=self.stubborn if applied else {AMEND_ROW, PUSH_ROW})


class Watching(Operator):
    """The person at the terminal, with the agent's configuration as it was at each question."""

    def __init__(self, home: Home, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.home = home
        self.texts: list[str] = []

    def __call__(self, prompt: str) -> str:
        exists = self.home.config.exists()
        self.texts.append(self.home.config.read_text() if exists else "")
        return super().__call__(prompt)


@pytest.fixture
def events() -> list[str]:
    return []


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Home:
    """A scratch agent home whose configuration holds entries of the person's own and a toolset."""
    scratch = Home(tmp_path, monkeypatch)
    scratch.holds(OWN, CURRENT_TOOLSET)
    return scratch


def installed(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
    runtime: SelectableRuntime,
    **kwargs,
) -> Path:
    """A planning repo whose runtime starts the known agent that has an applier."""
    kwargs.setdefault("command", list(AGENT.variants[0].argv))
    return configured(tmp_path, app, monkeypatch, runtime, **kwargs)


def without_policy_fix(planning: Path, name: str) -> None:
    """The installation's abk.yaml with `runtimes.<name>.policy_fix` removed."""
    path = planning / "abk.yaml"
    raw = yaml.safe_load(path.read_text())
    del raw["runtimes"][name]["policy_fix"]
    path.write_text(yaml.safe_dump(raw))


def policy_only(planning: Path, *flags: str) -> list[str]:
    return ["init", str(planning), "--policy-only", *flags]


def test_the_kit_s_fix_is_offered_with_the_path_and_diff_and_a_yes_applies_it(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    home: Home,
    events: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    planning = installed(tmp_path, app, monkeypatch, ConfigRuntime(home, log=events))
    events.clear()
    before = home.config.read_text()
    operator = Watching(home, capfd, "y", log=events)
    monkeypatch.setattr(init_cmd, "ask", operator)

    assert main(policy_only(planning)) == 0

    assert events == ["check", "ask", "check"]
    offer = operator.screens[0]
    assert str(home.config) in offer
    assert "+++" in offer
    assert patterns()[0] in offer
    assert operator.texts == [before]
    assert home.deny() == [*OWN, *patterns()]
    after = capfd.readouterr().out
    # Told, per class and spelling, what the second check observed.
    assert AMEND in after
    assert command_of(AMEND, AMEND_ROW[1]) in after
    assert command_of(PUSH, PUSH_ROW[1]) in after
    assert "refuses every forbidden class" in after


def test_a_no_writes_nothing_states_the_missing_guarantee_and_exits_one(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    home: Home,
    events: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    planning = installed(tmp_path, app, monkeypatch, ConfigRuntime(home, log=events))
    before = home.config.read_text()
    monkeypatch.setattr(init_cmd, "ask", Operator(capfd, "n"))

    assert main(policy_only(planning)) == 1

    assert home.config.read_text() == before
    assert home.files() == [home.config.name]
    shown = capfd.readouterr()
    said = shown.out + shown.err
    assert "still unenforced" in said
    assert command_of(AMEND, AMEND_ROW[1]) in said


def test_a_configured_fix_is_the_one_offered_when_both_exist(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    home: Home,
    events: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    fix = changing_nothing(tmp_path, "own-fix.sh")
    planning = installed(
        tmp_path, app, monkeypatch, ConfigRuntime(home, log=events), policy_fix=fix
    )
    before = home.config.read_text()
    operator = Operator(capfd, "y")
    monkeypatch.setattr(init_cmd, "ask", operator)
    real_fixes(monkeypatch)

    main(policy_only(planning))

    assert fix[0] in operator.screens[0]
    assert "recommended" not in operator.screens[0]
    assert home.config.read_text() == before

    # Without a configured fix, the kit's is what is offered.
    without_policy_fix(planning, "builtin")
    main(policy_only(planning))

    assert str(home.config) in operator.screens[-1]
    assert "+++" in operator.screens[-1]


def test_policy_fix_still_records_and_runs_the_person_s_own_fix(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    home: Home,
    events: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    fix = changing_nothing(tmp_path, "own-fix.sh")
    planning = installed(tmp_path, app, monkeypatch, ConfigRuntime(home, log=events))
    before = home.config.read_text()
    operator = Operator(capfd, "y")
    monkeypatch.setattr(init_cmd, "ask", operator)
    real_fixes(monkeypatch)

    main(policy_only(planning, "--policy-fix", fix[0]))

    assert recorded(planning, "builtin")["policy_fix"] == fix
    assert "recommended" not in "".join(operator.screens)
    assert home.config.read_text() == before

    # Remove it again, and the kit's fix is what the step offers.
    without_policy_fix(planning, "builtin")
    main(policy_only(planning))

    assert "+++" in operator.screens[-1]


def test_a_spelling_the_kit_s_fix_leaves_open_is_named_with_the_matcher_note(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    home: Home,
    events: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    runtime = ConfigRuntime(home, stubborn=(PUSH_ROW,), log=events)
    planning = installed(tmp_path, app, monkeypatch, runtime)
    monkeypatch.setattr(init_cmd, "ask", Operator(capfd, "y"))

    assert main(policy_only(planning)) == 1

    shown = capfd.readouterr()
    after = shown.out + shown.err
    assert home.deny() == [*OWN, *patterns()]
    assert "refuses every forbidden class" not in after
    assert "not refused" in after
    assert command_of(PUSH, PUSH_ROW[1]) in after.split("not refused")[-1]
    assert "matcher" in after


def test_yes_alone_runs_no_fix_names_the_unrefused_classes_and_exits_one(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    home: Home,
    events: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    planning = installed(tmp_path, app, monkeypatch, ConfigRuntime(home, log=events))
    before = home.config.read_text()

    assert main(policy_only(planning, "--yes")) == 1

    shown = capfd.readouterr()
    assert AMEND in shown.out + shown.err
    assert PUSH in shown.out + shown.err
    assert home.config.read_text() == before
    assert home.files() == [home.config.name]

    # With the authorising flag the same run applies it.
    assert main(policy_only(planning, "--yes", "--run-policy-fix")) == 0
    assert home.deny() == [*OWN, *patterns()]


def test_yes_with_the_authorising_flag_applies_without_asking(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    home: Home,
    events: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planning = installed(tmp_path, app, monkeypatch, ConfigRuntime(home, log=events))

    def refuse(prompt: str) -> str:
        pytest.fail(f"asked {prompt!r}")

    monkeypatch.setattr(init_cmd, "ask", refuse)

    assert main(policy_only(planning, "--yes", "--run-policy-fix")) == 0

    assert home.deny() == [*OWN, *patterns()]


def test_a_token_spending_check_is_asked_about_before_the_kit_s_fix(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    home: Home,
    events: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    runtime = ConfigRuntime(home, log=events, prompts=True)
    planning = installed(tmp_path, app, monkeypatch, runtime)
    events.clear()
    operator = Operator(capfd, "y", "y", log=events)
    monkeypatch.setattr(init_cmd, "ask", operator)

    assert main(policy_only(planning)) == 0

    assert events == ["ask", "check", "ask", "check"]
    assert "token" in operator.screens[0].lower()
    assert str(home.config) in operator.screens[1]


def test_an_absent_configuration_is_said_to_be_not_found_and_nothing_is_offered(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    events: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    empty = Home(tmp_path, monkeypatch)
    planning = installed(tmp_path, app, monkeypatch, ConfigRuntime(empty, log=events))
    events.clear()
    operator = Operator(capfd, otherwise="y", log=events)
    monkeypatch.setattr(init_cmd, "ask", operator)

    assert main(policy_only(planning)) == 1

    shown = capfd.readouterr()
    said = (shown.out + shown.err).lower()
    assert "not found" in said
    assert "abk policy patterns" in said
    assert "ask" not in events
    assert empty.files() == []


def test_an_agent_with_no_applier_lists_printing_the_patterns_among_its_choices(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    home: Home,
    events: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    planning = installed(
        tmp_path,
        app,
        monkeypatch,
        ConfigRuntime(home, log=events),
        command=list(BARE.variants[0].argv),
    )
    operator = Operator(capfd, "1")
    monkeypatch.setattr(init_cmd, "ask", operator)

    main(policy_only(planning))

    assert "abk policy patterns" in operator.screens[0]
    assert "recommended policy" not in operator.screens[0]


def test_after_the_kit_s_fix_the_toolset_is_unchanged_and_the_command_for_it_is_named(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    home: Home,
    events: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    planning = installed(tmp_path, app, monkeypatch, ConfigRuntime(home, log=events))
    monkeypatch.setattr(init_cmd, "ask", Operator(capfd, "y"))

    assert main(policy_only(planning)) == 0

    shown = capfd.readouterr()
    assert home.toolset() == CURRENT_TOOLSET
    assert "abk policy apply --toolset" in shown.out + shown.err
