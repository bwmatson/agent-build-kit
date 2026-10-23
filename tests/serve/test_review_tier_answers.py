"""The review route and the pipeline summary carry a unit's recorded review tier (spec:
review-triage): the route also its reason and the stored focus and skippable lists, and a unit
with no verdict is answered as before."""

from __future__ import annotations

import logging

import httpx
import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.verdict import ReviewTier
from agent_build_kit.pipeline.verdict_record import VERDICTS
from tests.factories import brief_description
from tests.review_repo import seed_branches
from tests.serving import seed_pipeline, seed_review_round
from tests.verdict_fakes import write_verdicts

UNIT = "feature/2"
REVIEW = f"/api/units/{UNIT}/review"
FIELDS = ("tier", "reason", "focus", "skippable")


@pytest.fixture
def seeded(inst: Installation, api: httpx.Client) -> httpx.Client:
    seed_pipeline(inst)
    seed_branches(inst)
    seed_review_round(inst, UNIT, 1)
    return api


def record(inst: Installation, tier: ReviewTier) -> None:
    write_verdicts(inst.state_dir / VERDICTS, {UNIT: tier})


def describe(inst: Installation) -> None:
    UnitStore(inst.state_dir / "units.json").record_approval(
        UNIT,
        "abc123",
        brief_description(
            focus=[("src/reader.py", "the new branch")], skippable=[("docs/notes.md", "prose only")]
        ),
    )


def test_the_review_route_holds_the_tier_reason_and_both_lists(
    inst: Installation, seeded: httpx.Client
) -> None:
    record(inst, ReviewTier.FULL)
    describe(inst)

    body = seeded.get(REVIEW).json()

    assert body["tier"] == "full"
    assert body["reason"] == "because"
    assert body["focus"] == [{"place": "src/reader.py", "reason": "the new branch"}]
    assert body["skippable"] == [{"place": "docs/notes.md", "reason": "prose only"}]


def test_the_pipeline_answer_carries_each_units_tier(
    inst: Installation, seeded: httpx.Client
) -> None:
    record(inst, ReviewTier.LIGHT)

    listed = {item["id"]: item for item in seeded.get("/api/pipeline").json()["units"]}

    assert listed[UNIT]["tier"] == "light"
    assert "tier" not in listed["feature/1"], "a unit with no verdict has no tier"


def test_a_unit_with_no_verdict_has_neither_field(seeded: httpx.Client) -> None:
    body = seeded.get(REVIEW).json()

    assert not any(field in body for field in FIELDS)
    assert "tier" not in seeded.get("/api/pipeline").json()["units"][1]


def test_an_unreadable_verdict_file_gives_the_answer_of_before_and_is_logged(
    inst: Installation, seeded: httpx.Client, caplog: pytest.LogCaptureFixture
) -> None:
    before = seeded.get(REVIEW).json()
    (inst.state_dir / VERDICTS).write_text("{ not json")

    with caplog.at_level(logging.WARNING):
        answer = seeded.get(REVIEW)
        listed = seeded.get("/api/pipeline")

    assert answer.status_code == 200
    assert answer.json() == before
    assert listed.status_code == 200
    assert not any("tier" in item for item in listed.json()["units"])
    assert any(VERDICTS in record.getMessage() for record in caplog.records)
