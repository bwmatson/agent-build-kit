"""The pipeline skill tells standing causes from event causes and what a replan keeps."""

from __future__ import annotations

import re

from agent_build_kit import skills
from tests.prompt_text import flat


def sentences(text: str) -> list[str]:
    return re.split(r"(?<=[.;:])\s+", flat(text).lower())


def test_the_pipeline_skill_names_standing_and_event_causes() -> None:
    text = flat(skills.source("abk-pipeline")).lower()

    assert "standing cause" in text
    assert "event cause" in text
    assert any("event cause" in s and "ends" in s and "standing" in s for s in sentences(text))


def test_the_pipeline_skill_says_a_replan_keeps_the_cause_the_parked_splits_and_the_requeue() -> (
    None
):
    kept = [
        s
        for s in sentences(skills.source("abk-pipeline"))
        if "replan" in s and ("keeps" in s or "carries" in s)
    ]

    assert any("cause" in s and "parked split" in s and "requeue" in s for s in kept), kept


def test_the_pipeline_skill_still_says_a_record_with_no_cause_is_never_readmitted_by_a_pass() -> (
    None
):
    text = flat(skills.source("abk-pipeline")).lower()

    assert re.search(r"no cause[^.]*never readmitted", text)
