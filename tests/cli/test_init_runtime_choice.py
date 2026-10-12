"""`abk init` asks which runtime, records the choice and hands it to the agent steps.

The machine is faked at the probe: which programs are on the path. A runtime's
candidate is usable when its `<name>-bin` is there. At the terminal "back" returns
to the list, and the list's last line is the person's own configuration.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from agent_build_kit import runtimes
from agent_build_kit.cli import main
from agent_build_kit.config import load
from agent_build_kit.init.runtime_choice import RuntimeChoiceError, choose
from agent_build_kit.runtimes.base import Question, QuestionKind
from tests.cli.init_choice_fakes import Answers, Offering, answering, machine, no_model
from tests.cli.test_init import app, init_args, stubs  # noqa: F401 — fixtures
from tests.factories import recognised_planning

ENV_PROMPT = "names of the environment variables the agent reads"


@pytest.fixture
def events() -> list[str]:
    return []


@pytest.fixture
def planning(tmp_path: Path) -> Path:
    return recognised_planning(tmp_path / "planning")


def listing(planning: Path) -> list[str]:
    return sorted(p.name for p in planning.iterdir())


def loaded_quietly(planning: Path, caplog: pytest.LogCaptureFixture):
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        config = load(planning / "abk.yaml")
    assert caplog.records == []
    return config


# --- the list and the question --------------------------------------------------------


def test_yes_with_nothing_usable_says_what_each_needs_exits_2_and_writes_nothing(
    planning: Path,
    app: Path,  # noqa: F811 — fixture
    events: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    machine(
        monkeypatch,
        (),
        Offering("alpha", events=events),
        Offering("beta", events=events),
        events=events,
    )
    before = listing(planning)

    code = main(init_args(planning, app, "--yes"))

    out = capsys.readouterr()
    assert code == 2
    assert "alpha-bin is not on the path" in out.out + out.err
    assert "beta-bin is not on the path" in out.out + out.err
    assert listing(planning) == before


def test_enter_records_the_only_usable_candidate_and_asks_for_no_fallback(
    planning: Path,
    app: Path,  # noqa: F811 — fixture
    events: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    machine(
        monkeypatch,
        ("alpha-bin",),
        Offering("alpha", events=events),
        Offering("beta", events=events),
        events=events,
    )
    answers = answering(monkeypatch, Answers())

    code = main(init_args(planning, app))

    config = load(planning / "abk.yaml")
    assert code == 0
    assert config.runtime == "alpha"
    assert config.runtimes["alpha"].command == ["alpha-bin", "acp"]
    assert not any("fallback" in prompt.lower() for prompt in answers.prompts)


def test_the_second_candidate_picked_is_written_with_usable_ones_listed_first(
    planning: Path,
    app: Path,  # noqa: F811 — fixture
    events: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Alphabetical order puts the unusable one first; the list must not.
    machine(
        monkeypatch,
        ("bravo-bin", "charlie-bin"),
        Offering("aardvark", events=events),
        Offering("bravo", events=events),
        Offering("charlie", events=events),
        events=events,
    )
    answering(monkeypatch, Answers("2"))

    code = main(init_args(planning, app))

    shown = capsys.readouterr().out
    assert code == 0
    assert shown.index("bravo agent") < shown.index("charlie agent")
    assert shown.index("charlie agent") < shown.index("aardvark agent")
    assert "aardvark-bin is not on the path" in shown
    assert shown.rindex("Other") > shown.index("aardvark agent")
    assert load(planning / "abk.yaml").runtime == "charlie"


def test_the_persons_own_argv_is_recorded_and_a_program_off_the_path_asked_again(
    planning: Path,
    app: Path,  # noqa: F811 — fixture
    events: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    alpha = Offering("alpha", events=events)
    machine(monkeypatch, ("mine-bin",), alpha, events=events)
    # The one candidate is unusable, so the list is it and the last line.
    answers = answering(monkeypatch, Answers("2", "nowhere-bin serve", "mine-bin serve"))

    code = main(init_args(planning, app))

    config = load(planning / "abk.yaml")
    assert code == 0
    assert "nowhere-bin is not on the path" in capsys.readouterr().out
    assert len([p for p in answers.prompts if alpha.command_prompt in p]) == 2
    assert config.runtime == "alpha"
    assert config.runtimes["alpha"].command == ["mine-bin", "serve"]


def test_going_back_shows_the_list_again_and_another_runtime_can_be_chosen(
    planning: Path,
    app: Path,  # noqa: F811 — fixture
    events: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    machine(
        monkeypatch,
        ("alpha-bin", "beta-bin"),
        Offering("alpha", events=events),
        Offering("beta", events=events),
        events=events,
    )
    answering(monkeypatch, Answers("1", "back", "2"))

    code = main(init_args(planning, app))

    assert code == 0
    assert capsys.readouterr().out.count("alpha agent") >= 2
    assert load(planning / "abk.yaml").runtime == "beta"


def test_a_wrapper_for_a_runtime_the_kept_file_already_configures_replaces_its_command(
    planning: Path,
    app: Path,  # noqa: F811 — fixture
    events: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    machine(
        monkeypatch,
        ("alpha-bin", "beta-bin", "wrapper-bin"),
        Offering("alpha", events=events),
        Offering("beta", events=events),
        events=events,
    )
    assert main(init_args(planning, app, "--yes", "--runtime", "alpha")) == 0
    answering(monkeypatch, Answers("y"))
    assert main(init_args(planning, app, "--runtime", "beta")) == 0

    answers = answering(monkeypatch, Answers("y"))
    code = main(
        init_args(planning, app, "--runtime", "alpha", "--agent-command", "wrapper-bin --flag")
    )

    config = load(planning / "abk.yaml")
    assert code == 0
    assert config.runtime == "alpha"
    assert config.runtimes["alpha"].command == ["wrapper-bin", "--flag"]
    assert config.runtimes["beta"].command == ["beta-bin", "acp"]
    # beta is already configured in the file: it is not offered again as a fallback.
    assert not any("fallback" in prompt for prompt in answers.prompts)


def test_an_agent_command_left_unrecorded_by_a_kept_file_is_said_so(
    planning: Path,
    app: Path,  # noqa: F811 — fixture
    events: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    machine(
        monkeypatch,
        ("alpha-bin", "wrapper-bin"),
        Offering("alpha", events=events),
        events=events,
    )
    assert main(init_args(planning, app, "--yes", "--runtime", "alpha")) == 0
    kept = (planning / "abk.yaml").read_text()
    capsys.readouterr()

    assert main(init_args(planning, app, "--agent-command", "wrapper-bin --flag")) == 0

    assert (planning / "abk.yaml").read_text() == kept
    assert "left as they are" in capsys.readouterr().out


def test_a_question_default_is_used_when_no_candidate_offers_one(
    events: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    machine(monkeypatch, (), Offering("alpha", events=events), events=events)

    with pytest.raises(RuntimeChoiceError, match="alpha-bin is not on the path"):
        choose([], ask=Answers(), which=lambda _: None, base={}, yes=True, runtime="alpha")


def test_a_wrapper_given_for_the_current_runtime_is_recorded(
    planning: Path,
    app: Path,  # noqa: F811 — fixture
    events: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    machine(
        monkeypatch,
        ("alpha-bin", "wrapper-bin"),
        Offering("alpha", events=events),
        events=events,
    )
    answering(monkeypatch, Answers("1", "wrapper-bin --flag"))

    code = main(init_args(planning, app))

    assert code == 0
    assert load(planning / "abk.yaml").runtimes["alpha"].command == ["wrapper-bin", "--flag"]


# --- --yes, --runtime, --agent-command and a kept file -------------------------------------


def test_yes_with_several_usable_refuses_with_the_list_until_a_runtime_is_named(
    planning: Path,
    app: Path,  # noqa: F811 — fixture
    events: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    machine(
        monkeypatch,
        ("alpha-bin", "beta-bin"),
        Offering("alpha", events=events),
        Offering("beta", events=events),
        events=events,
    )
    before = listing(planning)

    refused = main(init_args(planning, app, "--yes"))

    out = capsys.readouterr()
    assert refused == 2
    assert "alpha agent" in out.out + out.err
    assert "beta agent" in out.out + out.err
    assert listing(planning) == before

    named = main(
        init_args(planning, app, "--yes", "--runtime", "beta", "--agent-command", "beta-bin serve")
    )

    assert named == 0
    config = load(planning / "abk.yaml")
    assert config.runtime == "beta"
    assert config.runtimes["beta"].command == ["beta-bin", "serve"]


@pytest.mark.parametrize(
    "flags",
    [
        ("--runtime", "gamma"),
        ("--runtime", "alpha", "--agent-command", "nowhere-bin serve"),
        ("--runtime", "alpha", "--agent-command", ""),
    ],
    ids=["unknown name", "program off the path", "empty argv"],
)
def test_a_flag_the_validators_refuse_exits_2_and_writes_nothing(
    flags: tuple[str, ...],
    planning: Path,
    app: Path,  # noqa: F811 — fixture
    events: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    machine(monkeypatch, ("alpha-bin",), Offering("alpha", events=events), events=events)
    before = listing(planning)

    code = main(init_args(planning, app, "--yes", *flags))

    assert code == 2
    assert listing(planning) == before


def test_a_kept_file_that_names_a_runtime_skips_the_question_and_runtime_overrides_on_a_yes(
    planning: Path,
    app: Path,  # noqa: F811 — fixture
    events: list[str],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    machine(
        monkeypatch,
        ("alpha-bin", "beta-bin"),
        Offering("alpha", events=events),
        Offering("beta", events=events),
        events=events,
    )
    assert main(init_args(planning, app, "--yes", "--runtime", "alpha")) == 0
    kept = (planning / "abk.yaml").read_text()

    # The stubs fail on any prompt: nothing is asked of a kept file naming a runtime.
    assert main(init_args(planning, app)) == 0
    assert (planning / "abk.yaml").read_text() == kept

    answering(monkeypatch, Answers("n"))
    assert main(init_args(planning, app, "--runtime", "beta")) == 0
    assert load(planning / "abk.yaml").runtime == "alpha"

    before = load(planning / "abk.yaml").model_dump(mode="json")
    answering(monkeypatch, Answers("y"))
    assert main(init_args(planning, app, "--runtime", "beta")) == 0
    config = loaded_quietly(planning, caplog)
    assert config.runtime == "beta"
    after = config.model_dump(mode="json")
    for key in before.keys() - {"runtime", "runtimes"}:
        assert after[key] == before[key]


def test_force_overrides_a_kept_runtime_without_asking(
    planning: Path,
    app: Path,  # noqa: F811 — fixture
    events: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    machine(
        monkeypatch,
        ("alpha-bin", "beta-bin"),
        Offering("alpha", events=events),
        Offering("beta", events=events),
        events=events,
    )
    assert main(init_args(planning, app, "--yes", "--runtime", "alpha")) == 0
    kept = (planning / "abk.yaml").read_text()

    assert main(init_args(planning, app, "--yes", "--runtime", "beta")) == 0
    assert (planning / "abk.yaml").read_text() == kept
    assert "--force overrides" in capsys.readouterr().out

    code = main(init_args(planning, app, "--yes", "--runtime", "beta", "--force"))

    assert code == 0
    assert load(planning / "abk.yaml").runtime == "beta"


# --- the agent steps ---------------------------------------------------------------------


def test_research_and_propose_receive_the_chosen_runtime_and_run_after_the_choice(
    planning: Path,
    app: Path,  # noqa: F811 — fixture
    events: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alpha = Offering("alpha", events=events)
    beta = Offering("beta", events=events)
    machine(monkeypatch, ("alpha-bin", "beta-bin", "wrapper-bin"), alpha, beta, events=events)
    no_model(monkeypatch)
    answering(monkeypatch, Answers("2", "wrapper-bin --flag", events=events))

    code = main(["init", str(planning), "--repo", str(app)])

    assert code == 0
    assert beta.requests
    assert alpha.requests == []
    assert {tuple(c) for c in beta.commands} == {("wrapper-bin", "--flag")}
    first_run = events.index("run")
    assert "probe" in events[:first_run]
    assert "ask" in events[:first_run]
    assert "ask" not in events[first_run:]


def test_a_single_usable_candidate_under_yes_is_chosen_before_any_agent_step(
    planning: Path,
    app: Path,  # noqa: F811 — fixture
    events: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alpha = Offering("alpha", events=events)
    machine(monkeypatch, ("alpha-bin",), alpha, Offering("beta", events=events), events=events)
    no_model(monkeypatch)

    code = main(["init", str(planning), "--repo", str(app), "--yes"])

    assert code == 0
    assert alpha.requests
    assert {tuple(c) for c in alpha.commands} == {("alpha-bin", "acp")}
    assert events.index("probe") < events.index("run")


def test_a_kept_file_hands_its_own_recorded_command_to_the_agent_steps(
    planning: Path,
    app: Path,  # noqa: F811 — fixture
    events: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alpha = Offering("alpha", events=events)
    machine(monkeypatch, ("alpha-bin", "wrapper-bin"), alpha, events=events)
    no_model(monkeypatch)
    args = ["init", str(planning), "--repo", str(app), "--yes"]
    recorded = ["--runtime", "alpha", "--agent-command", "wrapper-bin --flag"]
    assert main([*args, *recorded, "--skip-research", "--skip-propose"]) == 0
    assert alpha.requests == []

    assert main(args) == 0

    assert alpha.requests
    assert {tuple(c) for c in alpha.commands} == {("wrapper-bin", "--flag")}


def test_skipping_research_and_propose_runs_no_agent_step(
    planning: Path,
    app: Path,  # noqa: F811 — fixture
    events: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alpha = Offering("alpha", events=events)
    machine(monkeypatch, ("alpha-bin",), alpha, events=events)
    no_model(monkeypatch)

    code = main(init_args(planning, app, "--yes"))

    assert code == 0
    assert load(planning / "abk.yaml").runtime == "alpha"
    assert alpha.requests == []
    assert "run" not in events


# --- the written file ----------------------------------------------------------------------


def test_the_written_file_loads_without_warnings(
    planning: Path,
    app: Path,  # noqa: F811 — fixture
    events: list[str],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    machine(monkeypatch, ("alpha-bin",), Offering("alpha", events=events), events=events)

    assert main(init_args(planning, app, "--yes")) == 0

    assert loaded_quietly(planning, caplog).runtime == "alpha"


def test_a_fallback_accepted_is_configured_and_runtime_names_the_first(
    planning: Path,
    app: Path,  # noqa: F811 — fixture
    events: list[str],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    machine(
        monkeypatch,
        ("bravo-bin", "charlie-bin"),
        Offering("bravo", events=events),
        Offering("charlie", events=events),
        events=events,
    )
    answering(monkeypatch, Answers("1", by_keyword={"fallback": "y"}))

    code = main(init_args(planning, app))

    config = loaded_quietly(planning, caplog)
    assert code == 0
    assert config.runtime == "bravo"
    assert config.runtimes["bravo"].command == ["bravo-bin", "acp"]
    assert config.runtimes["charlie"].command == ["charlie-bin", "acp"]


def test_a_fallback_declined_configures_only_the_first(
    planning: Path,
    app: Path,  # noqa: F811 — fixture
    events: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    machine(
        monkeypatch,
        ("bravo-bin", "charlie-bin"),
        Offering("bravo", events=events),
        Offering("charlie", events=events),
        events=events,
    )
    answers = answering(monkeypatch, Answers("1"))

    assert main(init_args(planning, app)) == 0

    assert any("fallback" in prompt.lower() for prompt in answers.prompts)
    assert set(load(planning / "abk.yaml").runtimes) == {"bravo"}


# --- a runtime added later -----------------------------------------------------------------


def test_a_runtime_with_its_own_questions_is_asked_them_and_its_answers_written_where_it_says(
    planning: Path,
    app: Path,  # noqa: F811 — fixture
    events: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "hunter2-not-for-the-file"
    monkeypatch.setenv("FUTURE_TOKEN", secret)
    future = Offering(
        "future",
        events=events,
        questions=[
            Question(
                key="environment",
                prompt=f"The {ENV_PROMPT}",
                default="",
                kind=QuestionKind.TEXT,
                validator=lambda answer, which: None,
                writes_to="redact",
            )
        ],
    )
    machine(monkeypatch, ("future-bin",), future, events=events)
    answers = answering(monkeypatch, Answers(by_keyword={ENV_PROMPT: "FUTURE_TOKEN"}))

    code = main(init_args(planning, app))

    written = (planning / "abk.yaml").read_text()
    assert code == 0
    assert any(ENV_PROMPT in prompt for prompt in answers.prompts)
    assert load(planning / "abk.yaml").runtime == "future"
    assert "FUTURE_TOKEN" in written
    assert secret not in written
    assert not any(secret in prompt for prompt in answers.prompts)
    assert runtimes.get("future") is future
