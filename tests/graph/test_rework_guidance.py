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
    WHOLE_ASK,
    person_guidance,
)
from agent_build_kit.pipeline.unit_store import FeedbackSource, RequeueReason
from tests.factories import unit
from tests.graph_driver import fresh, tick
from tests.runner_fakes import rejecting

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
    "CHECKS_PROMPT": (CHECKS_PROMPT, "a6920c4beb9414ba"),
    "CHECKS_CONTINUATION": (CHECKS_CONTINUATION, "7c3f45aefe415332"),
    "REWORK_PROMPT": (REWORK_PROMPT, "cd35367766b54c6f"),
    "REWORK_CONTINUATION": (REWORK_CONTINUATION, "e8c0801d05a868e4"),
    "REVIEW_FEEDBACK_PROMPT": (REVIEW_FEEDBACK_PROMPT, "8bc3af2de3ba40bf"),
    "REVIEW_FEEDBACK_CONTINUATION": (REVIEW_FEEDBACK_CONTINUATION, "437cbfe78c1665c0"),
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
    "source", [FeedbackSource.UNIT_TEST, FeedbackSource.REVIEW], ids=["checks", "review"]
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


def test_a_unit_with_only_a_note_and_no_saved_failure_is_reworked_from_the_note(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    tick(tmp_path, recorder)
    prompts: list[str] = []

    def agent(prompt: str, **kwargs: Any) -> str:
        prompts.append(prompt)
        return recorder.claude(prompt, **kwargs)

    tick(tmp_path, recorder, event=requeue())
    tick(tmp_path, recorder, run=agent)

    [prompt] = prompts
    assert prompt.startswith(person_guidance(NOTE) + "Review asked for a change")
    assert prompt.index(NOTE) < prompt.index(WHOLE_ASK)
    assert recorder.store.get(UNIT).guidance == ""


def test_a_unit_with_no_work_on_its_branch_builds_tests_first_with_the_note(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    recorder.store.set_guidance(UNIT, NOTE)

    tick(tmp_path, recorder)

    assert recorder.events[:2] == ["claude:tests", "commit:test"]
    assert NOTE in recorder.prompts[0]
    assert NOTE in recorder.prompts[1], "the implementation step is told it too"
    assert "claude:rework" not in recorder.events
    assert recorder.store.get(UNIT).guidance == "", "cleared by the implementation commit"
    assert NOTE in "\n".join(recorder.contexts), "and the review judges against it"


def test_a_note_given_to_the_review_loop_s_rework_is_told_to_the_next_review(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    recorder.verdicts = [rejecting("rename the marker")]
    asked = False

    def review(**kwargs: Any) -> str:
        nonlocal asked
        if not asked:
            # The person's note arrives while the first round is out, so the rework it
            # asks for is the loop's, which the note is cleared in.
            asked = True
            recorder.store.set_guidance(UNIT, NOTE)
        return recorder.review(**kwargs)

    tick(tmp_path, recorder, run_review=review, run_rework_review=review)

    first, second = recorder.contexts
    assert NOTE not in first
    assert NOTE in second
    assert any(NOTE in prompt and "rename the marker" in prompt for prompt in recorder.prompts)
    assert recorder.store.get(UNIT).guidance == ""
