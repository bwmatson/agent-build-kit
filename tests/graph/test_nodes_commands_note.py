"""Each build step that tells an agent to run the checks gives it the repo's commands (spec:
build-prompts).

The agent is faked at the recorder's edge, which keeps each prompt it was handed.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit import profiles
from agent_build_kit.config import RepoConfig
from agent_build_kit.graph.state import EventKind, ResumeEvent
from agent_build_kit.pipeline.agent_commands import commands_note
from agent_build_kit.pipeline.changelog_convention import changelog_note
from agent_build_kit.pipeline.stack_runner import TESTS_PROMPT
from agent_build_kit.pipeline.unit_store import FeedbackSource, RequeueReason
from tests.agent_command_fakes import Silent, allowed, command
from tests.factories import scratch_app, unit
from tests.graph.agent_fakes import distinct_models
from tests.graph.test_adapt_in_the_restack_session import TRIED, Failing
from tests.graph.test_build_path import build
from tests.graph.test_session_continuation import CHANGE_PATH, OLD_REF, Sessions, agents
from tests.graph_driver import fresh, tick
from tests.runner_fakes import Recorder, rejecting

SECTION = "Commands you may run"
FAILING = "FAILED tests/test_marker.py::test_marks"
STEPS = ["tests", "implement", "checks", "review-feedback", "rework", "adapt"]


def repo_of(tmp_path: Path, **fields: Any) -> RepoConfig:
    return RepoConfig(path=tmp_path, slug="example/app", **fields)


def requeue() -> ResumeEvent:
    return ResumeEvent(kind=EventKind.REQUEUE, reason="requeue", requeue=RequeueReason.FROM_FAILURE)


def step_prompts(tmp_path: Path, repo: RepoConfig) -> dict[str, str]:
    """The full prompt each step hands the agent for a unit of `repo`, one run per step."""
    found: dict[str, str] = {}

    def run_in(name: str, setup: Callable[[Recorder], None] = lambda r: None) -> Recorder:
        where = tmp_path / name
        where.mkdir()
        recorder = fresh(where)
        setup(recorder)
        tick(where, recorder, repo_config=repo)
        return recorder

    built = run_in("tests")
    found["tests"], found["implement"] = built.prompts[:2]

    def failing(recorder: Recorder) -> None:
        recorder.unit_test_results = [(False, FAILING), (True, "")]

    found["checks"] = run_in("checks", failing).prompts[2]

    def reject(recorder: Recorder) -> None:
        recorder.verdicts = [rejecting("rename the marker")]

    found["review-feedback"] = run_in("review-feedback", reject).prompts[2]

    where = tmp_path / "rework"
    where.mkdir()
    recorder = fresh(where)
    tick(where, recorder, repo_config=repo)
    recorder.store.set_feedback(unit().id, "FEEDBACK", source=FeedbackSource.REVIEW)
    seen = len(recorder.prompts)
    tick(where, recorder, event=requeue(), repo_config=repo)
    tick(where, recorder, repo_config=repo)
    found["rework"] = recorder.prompts[seen]

    found["adapt"] = adapt_prompt(tmp_path / "adapt", repo)
    return found


def adapt_prompt(where: Path, repo: RepoConfig) -> str:
    """The full port prompt: the session of the earlier steps cannot be continued."""
    where.mkdir()
    distinct_models()
    recorder = fresh(where)
    runtime = Sessions(refuses="the session is gone")
    build(
        where,
        recorder,
        base="spec/c/2",
        branch_commits=lambda cwd, base: 2 + recorder.made,
        restack_onto=Failing(),
        reset_to=lambda tree, onto, keep: None,
        tests_in=lambda tree: {"tests/test_marker.py::test_marks"},
        tests_changed=lambda tree, ref: set(),
        repo_config=repo,
        **agents(runtime),
    )
    [port] = [r for r in runtime.built if OLD_REF in r.prompt and CHANGE_PATH in r.prompt][-1:]
    assert TRIED in port.prompt
    return port.prompt


@pytest.fixture
def python_prompts(tmp_path: Path) -> dict[str, str]:
    return step_prompts(tmp_path, repo_of(tmp_path))


def test_each_step_of_a_python_repo_gives_the_agent_the_note(
    tmp_path: Path, python_prompts: dict[str, str]
) -> None:
    note = commands_note(repo_of(tmp_path))

    assert note
    for step in STEPS:
        assert python_prompts[step].count(note) == 1, step


def test_a_repo_with_its_own_commands_gives_its_own(tmp_path: Path) -> None:
    own = [command("test", "uv run pytest -q tests/unit")]
    prompts = step_prompts(tmp_path, repo_of(tmp_path, agent_commands=own))

    note = commands_note(repo_of(tmp_path, agent_commands=own))
    assert "uv run pytest -q tests/unit" in note
    for step in STEPS:
        assert note in prompts[step], step
        assert "uv run pre-commit run --all-files" not in prompts[step], step


def test_a_repo_whose_profile_gives_none_and_has_no_override_gets_no_section(
    tmp_path: Path,
) -> None:
    assert commands_note(repo_of(tmp_path)), "another repo's does"

    with profiles.registered(Silent()):
        prompts = step_prompts(tmp_path, repo_of(tmp_path, profile="fake-silent"))

    for step in STEPS:
        assert SECTION not in prompts[step], step


def test_the_tests_prompt_for_the_scratch_app_names_commands_the_build_allows(
    tmp_path: Path,
) -> None:
    app = scratch_app(tmp_path / "app")
    assert not list(app.glob("AGENTS.md")) and not list(app.glob("CLAUDE.md"))
    repo = repo_of(app)
    note = commands_note(repo)

    prompt = TESTS_PROMPT.format(
        groups="1",
        change_dir="openspec/changes/feature",
        boundary="",
        changelog=changelog_note(app, repo),
        commands=note,
    )

    assert "uv run pytest -q" in prompt
    assert "uv run pre-commit run --all-files" in prompt
    named = [line.split(": ", 1)[1] for line in note.splitlines() if line.startswith("- ")]
    assert named
    for line in named:
        item = command("test", line.replace("<path>", "{path}").replace("<test id>", "{path}"))
        assert allowed(repo, item), line
