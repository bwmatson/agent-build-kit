"""`abk init` asks what a chosen agent needs and which models to use, from what needs
no model call: an agent's advertised list, Claude Code's documented aliases, or a typed
name. Nothing here sends a prompt to an agent."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from agent_build_kit.cli import init as init_cmd
from agent_build_kit.cli import main
from agent_build_kit.config import ModelsConfig
from agent_build_kit.runtimes import PolicyReport, policy_check
from agent_build_kit.runtimes.known_agents import KnownAgent, StartVariant
from tests.cli.init_choice_fakes import (
    Answers,
    Listing,
    ModelAnswers,
    Offering,
    answering,
    machine,
)
from tests.cli.test_init import app, init_args, stubs  # noqa: F401 — fixtures
from tests.factories import recognised_planning
from tests.runtimes.acp_agent import command, requests
from tests.runtimes.probe_fakes import Host, table


@pytest.fixture
def events() -> list[str]:
    return []


@pytest.fixture
def planning(tmp_path: Path) -> Path:
    return recognised_planning(tmp_path / "planning")


def written(planning: Path) -> dict[str, Any]:
    return yaml.safe_load((planning / "abk.yaml").read_text())


def named_models(planning: Path) -> dict[str, str]:
    """The roles abk.yaml's `models:` block names, with the names it gives."""
    return {k: v for k, v in (written(planning).get("models") or {}).items() if v}


# --- what a known agent needs --------------------------------------------------------------


def test_an_agent_that_needs_a_running_backend_is_asked_whether_it_runs_and_to_continue(
    planning: Path,
    app: Path,  # noqa: F811 — fixture
    events: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    machine(
        monkeypatch,
        ("alpha-bin",),
        Offering("alpha", events=events, note="a running gateway"),
        events=events,
    )
    # "continue anyway" first: the first question names the gateway, and the second may too.
    answers = answering(monkeypatch, Answers(by_keyword={"continue anyway": "y", "running": "n"}))

    code = main(init_args(planning, app))

    assert code == 0
    assert any("running" in p.lower() for p in answers.prompts)
    assert any("continue anyway" in p.lower() for p in answers.prompts)
    assert written(planning)["runtime"] == "alpha"


def test_continuing_anyway_is_not_asked_when_the_backend_is_running(
    planning: Path,
    app: Path,  # noqa: F811 — fixture
    events: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    machine(
        monkeypatch,
        ("alpha-bin",),
        Offering("alpha", events=events, note="a running gateway"),
        events=events,
    )
    answers = answering(monkeypatch, Answers(by_keyword={"running": "y"}))

    assert main(init_args(planning, app)) == 0

    assert any("running" in p.lower() for p in answers.prompts)
    assert not any("continue anyway" in p.lower() for p in answers.prompts)


# --- Claude Code: documented aliases --------------------------------------------------------


def no_agent_started(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nothing is run on the machine: the probe's runner and the agent steps' both fail."""

    def refuse(*args: object, **kwargs: object) -> None:
        pytest.fail("an agent or program was started")

    monkeypatch.setattr(init_cmd, "probe_run", refuse)
    monkeypatch.setattr(init_cmd, "run_claude", refuse)


def test_the_default_models_are_offered_first_and_accepting_them_names_no_other(
    planning: Path,
    app: Path,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    no_agent_started(monkeypatch)
    answers = answering(monkeypatch, ModelAnswers("", "", general=["1"]))

    code = main(init_args(planning, app))

    defaults = ModelsConfig()
    assert code == 0
    assert any("default" in p.lower() and "model" in p.lower() for p in answers.prompts)
    for role, name in named_models(planning).items():
        assert name == getattr(defaults, role)


def test_a_model_is_chosen_per_role_from_the_documented_aliases(
    planning: Path,
    app: Path,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    no_agent_started(monkeypatch)
    answering(
        monkeypatch,
        ModelAnswers("", "", general=["2"], per_role={"review": "sonnet", "implement": "haiku"}),
    )

    code = main(init_args(planning, app))

    shown = capsys.readouterr().out
    assert code == 0
    assert "documented" in shown
    assert named_models(planning)["review"] == "sonnet"
    assert named_models(planning)["implement"] == "haiku"


def test_typed_model_names_are_written_as_given_and_not_tested_by_asking(
    planning: Path,
    app: Path,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    no_agent_started(monkeypatch)
    typed = "a-name-no-list-has"
    answering(
        monkeypatch,
        ModelAnswers("", "", general=["3", typed], per_role={"review": typed}),
    )

    code = main(init_args(planning, app))

    assert code == 0
    assert typed in named_models(planning).values()


# --- a protocol agent: what it advertises -------------------------------------------------------


def stand_in_host(monkeypatch: pytest.MonkeyPatch, record: Path, models: tuple[str, ...]) -> None:
    """A machine whose only agent is a real protocol subprocess, listed as a known agent
    by a program on the faked path, that fails on any prompt it is sent."""
    argv = command(record, models=models, fail="error")
    host = Host(("svc-a", sys.executable))
    monkeypatch.setattr(init_cmd, "which", host.which)
    monkeypatch.setattr(init_cmd, "probe_run", host.run)
    table(
        monkeypatch,
        KnownAgent(
            name="Stand-in",
            program="svc-a",
            variants=(StartVariant(argv=tuple(argv)),),
            verified="documented only",
            source="https://example.test/svc-a",
        ),
    )
    monkeypatch.setattr(policy_check, "check_policy", lambda *a, **k: PolicyReport(ok=True))


def test_an_agent_advertising_models_shows_them_with_its_current_one_as_the_default(
    planning: Path,
    app: Path,  # noqa: F811 — fixture
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    record = tmp_path / "agent.jsonl"
    stand_in_host(monkeypatch, record, ("m-one", "m-two", "m-three"))
    answering(monkeypatch, ModelAnswers("", "", per_role={"review": "m-two"}))

    code = main(init_args(planning, app))

    shown = capsys.readouterr().out
    current = next(
        (line for line in shown.splitlines() if "m-one" in line and record.name not in line), ""
    )
    assert code == 0
    assert "default" in current.lower()
    assert "m-two" in shown and "m-three" in shown
    assert named_models(planning) == {"review": "m-two"}
    assert len(requests(record, "session/new")) >= 1
    assert requests(record, "session/prompt") == []


def test_an_agent_advertising_none_says_so_leaves_the_roles_empty_and_takes_a_typed_name(
    planning: Path,
    app: Path,  # noqa: F811 — fixture
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    stand_in_host(monkeypatch, tmp_path / "none.jsonl", ())
    answering(monkeypatch, ModelAnswers("", ""))

    assert main(init_args(planning, app)) == 0

    assert "does not list its models" in capsys.readouterr().out
    assert named_models(planning) == {}

    other = recognised_planning(tmp_path / "typed")
    answering(
        monkeypatch,
        ModelAnswers("", "", general=["typed-name"], per_role={"review": "typed-name"}),
    )

    assert main(init_args(other, app)) == 0

    assert "typed-name" in named_models(other).values()


def test_listing_models_opens_a_session_and_sends_no_prompt_to_an_agent_that_fails_on_one(
    planning: Path,
    app: Path,  # noqa: F811 — fixture
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = tmp_path / "agent.jsonl"
    stand_in_host(monkeypatch, record, ("m-one", "m-two"))
    answering(monkeypatch, ModelAnswers("", ""))

    code = main(init_args(planning, app))

    assert code == 0
    assert len(requests(record, "session/new")) >= 1
    assert requests(record, "session/prompt") == []


def test_an_offered_runtime_is_listed_against_the_command_chosen_before_it_is_written(
    planning: Path,
    app: Path,  # noqa: F811 — fixture
    events: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alpha = Listing("alpha", models=("a-1", "a-2"), events=events)
    machine(monkeypatch, ("alpha-bin", "wrapper-bin"), alpha, events=events)
    answering(monkeypatch, ModelAnswers("", "wrapper-bin --flag", per_role={"review": "a-2"}))

    assert main(init_args(planning, app)) == 0

    assert [list(c or []) for c in alpha.listed] == [["wrapper-bin", "--flag"]]
    assert named_models(planning) == {"review": "a-2"}


def test_a_fallback_whose_needs_are_declined_is_left_out_and_the_choice_stands(
    planning: Path,
    app: Path,  # noqa: F811 — fixture
    events: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    machine(
        monkeypatch,
        ("alpha-bin", "beta-bin"),
        Offering("alpha", events=events),
        Offering("beta", events=events, note="a running gateway"),
        events=events,
    )
    answering(
        monkeypatch,
        Answers("1", by_keyword={"fallback": "y", "continue anyway": "n", "running": "n"}),
    )

    code = main(init_args(planning, app))

    assert code == 0
    assert written(planning)["runtime"] == "alpha"
    assert "beta" not in written(planning)["runtimes"]


def test_the_advertised_list_is_numbered_with_the_agents_default_first(
    planning: Path,
    app: Path,  # noqa: F811 — fixture
    events: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    alpha = Listing("alpha", models=("a-1", "a-2", "a-3"), events=events, current=1)
    machine(monkeypatch, ("alpha-bin",), alpha, events=events)
    answering(monkeypatch, ModelAnswers("", "", per_role={"review": "2"}))

    assert main(init_args(planning, app)) == 0

    shown = capsys.readouterr().out
    assert shown.index("1. a-2 (default)") < shown.index("2. a-1") < shown.index("3. a-3")
    assert named_models(planning) == {"review": "a-1"}
