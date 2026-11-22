"""A rework agent is never handed a known secret value, even from feedback saved before
the value was known; assembling the prompt leaves the stored feedback as it was."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.graph.state import EventKind, ResumeEvent
from agent_build_kit.pipeline.unit_store import FeedbackSource, RequeueReason, UnitStore
from tests.factories import unit
from tests.graph_driver import fresh, tick
from tests.redaction_fakes import NAME, SECRET, known

UNIT = unit().id
SAVED = f"the run failed; it printed {SECRET} in its output"


def _requeue() -> ResumeEvent:
    return ResumeEvent(kind=EventKind.REQUEUE, reason="requeue", requeue=RequeueReason.FROM_FAILURE)


@pytest.mark.parametrize(
    "source", [FeedbackSource.UNIT_TEST, FeedbackSource.REVIEW], ids=["checks", "review"]
)
def test_the_prompt_holds_the_replacement_and_the_stored_feedback_is_unchanged(
    tmp_path: Path, source: FeedbackSource
) -> None:
    recorder = fresh(tmp_path)
    tick(tmp_path, recorder)
    recorder.store.set_feedback(UNIT, SAVED, source=source)
    prompts: list[str] = []
    stored: list[str] = []

    def agent(prompt: str, **kwargs: Any) -> str:
        prompts.append(prompt)
        stored.append(recorder.store.get(UNIT).feedback)
        return recorder.claude(prompt, **kwargs)

    with known():
        tick(tmp_path, recorder, event=_requeue())
        tick(tmp_path, recorder, run=agent)

    [prompt] = prompts
    assert SECRET not in prompt
    assert f"[redacted:{NAME}]" in prompt
    assert stored == [SAVED]


def test_a_fix_round_prompt_holds_the_replacement_and_the_stored_feedback_is_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Feedback saved before the value was known is raw in the store: a failed check's
    output is saved with the set empty, then the fix prompt is built with it known."""
    recorder = fresh(tmp_path)
    recorder.unit_test_results = [(False, f"FAILED tests/test_it.py - env={SECRET}"), (True, "")]
    save = UnitStore.set_feedback

    def save_before_the_value_was_known(*args: Any, **kwargs: Any) -> None:
        with known({}):
            save(*args, **kwargs)

    monkeypatch.setattr(UnitStore, "set_feedback", save_before_the_value_was_known)
    prompts: list[str] = []
    stored: list[str] = []

    def agent(prompt: str, **kwargs: Any) -> str:
        prompts.append(prompt)
        stored.append(recorder.store.get(UNIT).feedback)
        return recorder.claude(prompt, **kwargs)

    with known():
        tick(tmp_path, recorder, run=agent)

    fixes = [p for p in prompts if "checks (lint" in p]
    assert len(fixes) == 1
    assert SECRET not in fixes[0]
    assert f"[redacted:{NAME}]" in fixes[0]
    assert SECRET in stored[prompts.index(fixes[0])]
