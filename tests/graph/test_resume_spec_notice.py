"""A resumed session is told which of the change's spec files changed since its agent last
ran, and shown what was added; a fresh session reads the spec as it is and is told nothing
(docs/unit-graph.md, Session capture and resume).

The agent is a runtime behind the `AgentRuntime` seam, as in the session tests; the spec files
are real files under the planning repo, edited between two steps of the unit's thread.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit import config as config_module
from agent_build_kit.graph.state import EventKind, ResumeEvent, SessionRole
from agent_build_kit.runtimes import AgentRequest, AgentResult
from tests.graph.test_session_continuation import (
    CHANGE_PATH,
    FAILING,
    REWORK_ASK,
    Sessions,
    agents,
    failing_checks,
    reuse,
)
from tests.graph_driver import fresh, position, tick
from tests.runner_fakes import Recorder, rejecting

TASKS = """\
## 1. [app] [tier1] The marker

- [ ] 1.1 Test: the marker is registered
- [ ] 1.2 Register the marker

## 2. [app] [tier1] Someone else's group

- [ ] 2.1 Test: the other thing
"""
ADDED = "- [ ] 1.3 Test: the marker survives a restart"
ELSEWHERE = "- [ ] 2.2 Test: a task of the other group"
CUT = 6000


def change_dir(tmp_path: Path) -> Path:
    return tmp_path / "meta" / CHANGE_PATH


def write_spec(tmp_path: Path) -> None:
    """The change as the agent first sees it: tasks, a design, one delta spec."""
    where = change_dir(tmp_path)
    (where / "specs" / "marker").mkdir(parents=True, exist_ok=True)
    (where / "tasks.md").write_text(TASKS)
    (where / "design.md").write_text("## Context\n\nThe marker is a flag.\n")
    (where / "specs" / "marker" / "spec.md").write_text("## ADDED Requirements\n\nA marker.\n")


def append(path: Path, text: str) -> None:
    path.write_text(path.read_text() + text)


def add_task(tasks: Path) -> None:
    """A task in the unit's own group 1."""
    tasks.write_text(TASKS.replace("- [ ] 1.2", f"{ADDED}\n- [ ] 1.2"))


def edited_in_tier1(recorder: Recorder, edit: Callable[[], object]) -> Callable[..., Any]:
    """Tier 1 failing once, the person's edit landing as it runs, then passing."""
    recorder.tier1_results = [(False, FAILING), (True, "")]
    first = [True]

    def run_tier1(**kw: Any) -> tuple[bool, str]:
        if first:
            first.clear()
            edit()
        return recorder.tier1(**kw)

    return run_tier1


class EditedAtReview(Sessions):
    """The runtime of the session tests, the spec edited as the first review begins."""

    def __init__(self, edit: Callable[[], None]) -> None:
        super().__init__(verdicts=[rejecting(REWORK_ASK)])
        self.edit = edit

    def run(self, request: AgentRequest) -> AgentResult:
        if request.role == "review" and not self.judged:
            self.edit()
        return super().run(request)


def resumed_fix(tmp_path: Path, edit: Callable[[], object]) -> str:
    """The prompt of the build step that resumes the session after a failed check, the
    spec edited by `edit` between the implementation and the check."""
    write_spec(tmp_path)
    recorder = fresh(tmp_path)
    runtime = Sessions()
    tick(tmp_path, recorder, run_tier1=edited_in_tier1(recorder, edit), **agents(runtime))
    fix = runtime.built[2]
    assert fix.resume_session == "sess-1" and FAILING in fix.prompt
    return fix.prompt


def test_an_added_task_is_named_and_shown_to_the_resumed_session(tmp_path: Path) -> None:
    tasks = change_dir(tmp_path) / "tasks.md"
    prompt = resumed_fix(tmp_path, lambda: add_task(tasks))

    assert "tasks.md" in prompt
    assert ADDED in prompt
    assert "design.md" not in prompt, "an unchanged file adds nothing"
    assert "spec.md" not in prompt


@pytest.mark.parametrize(
    ("file", "line"),
    [
        ("design.md", "The marker is kept in the run state."),
        ("specs/marker/spec.md", "#### Scenario: a marker is shown"),
    ],
)
def test_a_changed_design_or_spec_file_is_named_with_the_added_lines(
    tmp_path: Path, file: str, line: str
) -> None:
    path = change_dir(tmp_path) / file
    prompt = resumed_fix(tmp_path, lambda: append(path, f"{line}\n"))

    assert file.rsplit("/", 1)[-1] in prompt
    assert line in prompt
    assert "tasks.md" not in prompt


def test_only_the_units_own_groups_of_tasks_are_compared(tmp_path: Path) -> None:
    tasks = change_dir(tmp_path) / "tasks.md"

    def edit() -> None:
        text = TASKS.replace("- [ ] 2.1", f"{ELSEWHERE}\n- [ ] 2.1")
        tasks.write_text(text.replace("- [ ] 1.2", f"{ADDED}\n- [ ] 1.2"))

    prompt = resumed_fix(tmp_path, edit)

    assert ADDED in prompt
    assert ELSEWHERE not in prompt


def test_a_diff_over_the_cut_keeps_the_first_6000_characters_and_points_to_the_file(
    tmp_path: Path,
) -> None:
    design = change_dir(tmp_path) / "design.md"
    lines = [f"line-{n:04d} {'x' * 70}" for n in range(200)]
    assert sum(len(line) + 1 for line in lines) > 2 * CUT
    prompt = resumed_fix(tmp_path, lambda: append(design, "\n".join(lines) + "\n"))

    assert lines[0] in prompt
    assert lines[-1] not in prompt
    assert lines[CUT // 80 + 5] not in prompt, "cut at 6000 characters, not by lines kept whole"
    assert str(design) in prompt, "says where the rest is"
    assert len(prompt) < len(FAILING) + 2 * CUT


def test_a_rework_continuation_is_told_too(tmp_path: Path) -> None:
    write_spec(tmp_path)
    tasks = change_dir(tmp_path) / "tasks.md"
    runtime = EditedAtReview(lambda: add_task(tasks))

    tick(tmp_path, fresh(tmp_path), **agents(runtime))

    *_, rework = runtime.built
    assert rework.resume_session == "sess-1" and REWORK_ASK in rework.prompt
    assert "tasks.md" in rework.prompt
    assert ADDED in rework.prompt


def test_a_session_that_ran_with_nothing_edited_since_is_told_nothing_of_the_spec(
    tmp_path: Path,
) -> None:
    write_spec(tmp_path)
    recorder = fresh(tmp_path)
    failing_checks(recorder)
    runtime = Sessions()

    tick(tmp_path, recorder, **agents(runtime))

    state = position(tmp_path).state
    assert state is not None and state.sessions[SessionRole.BUILD].spec, "what it saw is kept"
    fix = runtime.built[2]
    assert fix.resume_session == "sess-1"
    for name in ("tasks.md", "design.md", "spec.md"):
        assert name not in fix.prompt


def test_a_fresh_session_is_given_no_section_for_the_spec_that_changed(tmp_path: Path) -> None:
    write_spec(tmp_path)
    reuse(build=False)
    tasks = change_dir(tmp_path) / "tasks.md"
    recorder = fresh(tmp_path)
    runtime = Sessions()

    tick(
        tmp_path,
        recorder,
        run_tier1=edited_in_tier1(recorder, lambda: add_task(tasks)),
        **agents(runtime),
    )

    state = position(tmp_path).state
    assert state is not None and state.sessions[SessionRole.BUILD].spec
    *_, fix = runtime.built
    assert fix.resume_session == "" and FAILING in fix.prompt
    assert ADDED not in fix.prompt


def test_the_copies_an_agent_run_leaves_are_removed_when_the_unit_merges(tmp_path: Path) -> None:
    write_spec(tmp_path)
    root = config_module.active_root()
    assert root is not None
    kept = root / config_module.active().planning.state_dir / "spec-snapshots" / "add-marker" / "1"
    recorder = fresh(tmp_path)

    tick(tmp_path, recorder, **agents(Sessions()))

    assert (kept / "build" / "tasks.md").read_text() == TASKS
    tick(tmp_path, recorder, event=ResumeEvent(kind=EventKind.MERGED, reason="merged"))
    assert not kept.exists()
