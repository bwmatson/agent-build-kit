"""A person's note, given with `abk requeue --note`, reaches the agent ahead of whatever else
a rework hands it, and the review of the work that follows is told it too.

The six templates are checked as text, the guidance placed ahead of the feedback; a unit
with no guidance renders each one byte for byte as before. The node is driven through the
thread, with the agent faked, for the stored note: it is cleared by the rework commit.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.graph.state import EventKind, ResumeEvent
from agent_build_kit.pipeline.stack_runner import (
    CHECKS_CONTINUATION,
    CHECKS_PROMPT,
    REVIEW_FEEDBACK_CONTINUATION,
    REVIEW_FEEDBACK_PROMPT,
    REWORK_CONTINUATION,
    REWORK_PROMPT,
    person_guidance,
)
from agent_build_kit.pipeline.unit_store import FeedbackSource, RequeueReason
from tests.factories import unit
from tests.graph_driver import fresh, tick

UNIT = unit().id
NOTE = "give the date exactly as printed"
FEEDBACK = "FEEDBACK-TEXT"
FIELDS: dict[str, Any] = dict(
    change_dir="openspec/changes/feature",
    groups="1",
    feedback=FEEDBACK,
    boundary="",
    pr=7,
    changelog="",
)
# The first 16 hex digits of the SHA-256 of each template rendered with `FIELDS`, as they were
# before guidance existed.
TEMPLATES = {
    "CHECKS_PROMPT": (CHECKS_PROMPT, "1a19b1337bd2db03"),
    "CHECKS_CONTINUATION": (CHECKS_CONTINUATION, "204d1f2e89285c9a"),
    "REWORK_PROMPT": (REWORK_PROMPT, "b5906db7ed251484"),
    "REWORK_CONTINUATION": (REWORK_CONTINUATION, "6f56973708a450f6"),
    "REVIEW_FEEDBACK_PROMPT": (REVIEW_FEEDBACK_PROMPT, "3c47fa9a66b04edf"),
    "REVIEW_FEEDBACK_CONTINUATION": (REVIEW_FEEDBACK_CONTINUATION, "bc57686d72b57cb1"),
}


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


@pytest.mark.parametrize("name", TEMPLATES)
def test_a_template_shows_the_guidance_as_a_persons_instruction_ahead_of_the_feedback(
    name: str,
) -> None:
    template, before = TEMPLATES[name]

    with_note = template.format(**FIELDS, guidance=person_guidance(NOTE))
    without = template.format(**FIELDS, guidance=person_guidance(""))

    assert NOTE in with_note
    assert with_note.index(NOTE) < with_note.index(FEEDBACK)
    assert with_note.lower().count("person") > without.lower().count("person")
    assert digest(without) == before, "no guidance, no change to the text"


def requeue(guidance: str = NOTE) -> ResumeEvent:
    return ResumeEvent(
        kind=EventKind.REQUEUE,
        reason="requeue",
        requeue=RequeueReason.FROM_FAILURE,
        guidance=guidance,
    )


@pytest.mark.parametrize(
    "source", [FeedbackSource.TIER1, FeedbackSource.REVIEW], ids=["checks", "review"]
)
def test_a_reworked_unit_is_handed_the_note_ahead_of_its_saved_feedback(
    tmp_path: Path, source: FeedbackSource
) -> None:
    recorder = fresh(tmp_path)
    tick(tmp_path, recorder)
    recorder.store.set_feedback(UNIT, FEEDBACK, source=source)
    prompts: list[str] = []

    def agent(prompt: str, **kwargs: Any) -> str:
        prompts.append(prompt)
        return recorder.claude(prompt, **kwargs)

    tick(tmp_path, recorder, event=requeue())
    tick(tmp_path, recorder, run=agent)

    [prompt] = prompts
    assert prompt.index(NOTE) < prompt.index(FEEDBACK)


def test_the_rework_commit_clears_the_note_and_the_next_review_is_told_it(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    tick(tmp_path, recorder)
    recorder.store.set_feedback(UNIT, FEEDBACK, source=FeedbackSource.REVIEW)
    reviews = len(recorder.contexts)
    held: list[str] = []

    def agent(prompt: str, **kwargs: Any) -> str:
        held.append(recorder.store.get(UNIT).guidance)
        return recorder.claude(prompt, **kwargs)

    tick(tmp_path, recorder, event=requeue())
    tick(tmp_path, recorder, run=agent)

    assert held == [NOTE], "stored by the requeue, for the agent that runs"
    assert recorder.store.get(UNIT).guidance == "", "cleared where the rework commit is made"
    assert NOTE in "\n".join(recorder.contexts[reviews:]), "and the reviewer was told it"
