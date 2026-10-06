"""A rework delivered to a unit's thread always runs its agent; the guard that reads an
advanced branch as a step already done is for a step resumed within a run."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.graph.state import EventKind, ResumeEvent
from tests.graph_driver import fresh, tick
from tests.runner_fakes import Killed, rejecting

FEEDBACK = "[comment c1] src/app.py:3 — remove this line"


def rework_event() -> ResumeEvent:
    return ResumeEvent(kind=EventKind.REWORK, reason="comment", feedback=FEEDBACK, from_person=True)


def test_a_rework_is_run_though_the_branch_is_ahead_of_the_tip_the_thread_recorded(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    tick(tmp_path, recorder)
    assert "claude:rework" not in recorder.events
    # A previous run moved the branch after the thread last recorded its tip.
    recorder.made += 1

    tick(tmp_path, recorder, event=rework_event())
    tick(tmp_path, recorder)

    assert recorder.events.count("claude:rework") == 1, "the agent ran on the feedback"
    assert FEEDBACK in recorder.prompts[-1] or "remove this line" in "".join(recorder.prompts)
    assert not any("already on the branch" in line for line in recorder.logged)


def test_a_rework_step_cut_short_after_the_agent_committed_does_not_run_it_again(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    tick(tmp_path, recorder)
    tick(tmp_path, recorder, event=rework_event())
    # The first review of the rework asks for a change; the step that answers it
    # is killed once the agent has committed.
    recorder.verdicts = [rejecting("the lock is not released on error")]
    runs: list[str] = []

    def agent(prompt: str, **kwargs: Any) -> str:
        runs.append(prompt)
        if len(runs) == 2:
            recorder.kill_after = "commit:fix"
        return recorder.claude(prompt, **kwargs)

    with pytest.raises(Killed):
        tick(tmp_path, recorder, run_rework=agent)
    assert len(runs) == 2, "the delivered rework, then the review's ask"

    tick(tmp_path, recorder, run_rework=agent)

    assert len(runs) == 2, "the step was not run again on resume"
