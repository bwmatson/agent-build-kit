"""A rework agent is never handed a known secret value, even from feedback saved before
the value was known; assembling the prompt leaves the stored feedback as it was."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.graph.state import EventKind, ResumeEvent
from agent_build_kit.pipeline.unit_store import FeedbackSource, RequeueReason
from tests.factories import unit
from tests.graph_driver import fresh, tick
from tests.redaction_fakes import NAME, SECRET, known

UNIT = unit().id
SAVED = f"the run failed; it printed {SECRET} in its output"


def _requeue() -> ResumeEvent:
    return ResumeEvent(kind=EventKind.REQUEUE, reason="requeue", requeue=RequeueReason.FROM_FAILURE)


@pytest.mark.parametrize(
    "source", [FeedbackSource.TIER1, FeedbackSource.REVIEW], ids=["checks", "review"]
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
