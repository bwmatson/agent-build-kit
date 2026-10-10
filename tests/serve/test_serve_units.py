"""The pipeline and unit endpoints: a unit is addressed as `change/N` and its page
reads its state, cause, history and links from the record (spec: web-ui)."""

from __future__ import annotations

import httpx
import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_store import Cause, FeedbackSource, HeldBy, UnitStore
from agent_build_kit.pipeline.units import HELD, RUNNING
from tests.serving import EXPECTED, seed_pipeline, seed_review_round


@pytest.fixture
def pipeline(inst: Installation, api: httpx.Client) -> httpx.Client:
    seed_pipeline(inst)
    return api


def test_the_pipeline_lists_every_unit_with_its_effective_state(pipeline: httpx.Client) -> None:
    answer = pipeline.get("/api/pipeline")

    assert answer.status_code == 200
    listed = {item["id"]: item["status"] for item in answer.json()["units"]}
    assert listed == {uid: expected[0] for uid, expected in EXPECTED.items()}


def test_the_pipeline_keeps_the_stored_state_in_state_beside_the_derived_name(
    inst: Installation, pipeline: httpx.Client
) -> None:
    store = UnitStore(inst.state_dir / "units.json")
    store.set_feedback("feature/7", "rename it", source=FeedbackSource.REVIEW)
    store.set_state("feature/7", RUNNING, note="rework requested", cause=Cause.REWORK)

    listed = {item["id"]: item for item in pipeline.get("/api/pipeline").json()["units"]}

    assert (listed["feature/7"]["state"], listed["feature/7"]["status"]) == ("running", "reworking")
    assert (listed["feature/3"]["state"], listed["feature/3"]["status"]) == ("planned", "blocked")
    unit = pipeline.get("/api/units/feature/7").json()
    assert (unit["state"], unit["status"]) == ("running", "reworking")


@pytest.mark.parametrize("uid", sorted(EXPECTED))
def test_a_unit_answers_at_its_own_name_with_its_state_cause_and_note(
    pipeline: httpx.Client, uid: str
) -> None:
    state, cause, held_by, note = EXPECTED[uid]

    answer = pipeline.get(f"/api/units/{uid}")

    assert answer.status_code == 200
    body = answer.json()
    assert body["id"] == uid
    assert (body["status"], body["cause"], body["held_by"], body["note"]) == (
        state,
        cause,
        held_by,
        note,
    )


def test_a_held_unit_reports_its_holder_from_the_record_not_the_note(
    inst: Installation, pipeline: httpx.Client
) -> None:
    # The note names a different holder; the recorded one wins.
    UnitStore(inst.state_dir / "units.json").set_state(
        "feature/4",
        HELD,
        note="held by a reviewer",
        held_by=HeldBy.TOOLCHAIN,
        cause=Cause.TOOLCHAIN,
    )

    body = pipeline.get("/api/units/feature/4").json()

    assert (body["state"], body["held_by"], body["cause"]) == ("held", "toolchain", "toolchain")


def test_the_history_is_a_timeline_of_state_time_cause_and_note(pipeline: httpx.Client) -> None:
    body = pipeline.get("/api/units/feature/1").json()

    assert [(e["state"], e["cause"], e["note"]) for e in body["history"]] == [
        ("planned", None, ""),
        ("merged", "merged", ""),
        ("merged", "merged", "merged"),
    ]
    assert all(entry["at"] for entry in body["history"])


def test_a_unit_reports_its_branch_base_and_pull_request(pipeline: httpx.Client) -> None:
    middle = pipeline.get("/api/units/feature/2").json()
    stacked = pipeline.get("/api/units/feature/4").json()
    never_started = pipeline.get("/api/units/feature/8").json()

    assert (middle["branch"], middle["pr"], middle["base"]) == ("spec/feature/2", 12, "main")
    assert stacked["base"] == "spec/feature/2"
    assert (never_started["branch"], never_started["pr"]) == ("", None)


def test_a_unit_lists_its_dependencies_and_merge_gates_with_their_states(
    pipeline: httpx.Client,
) -> None:
    gated = pipeline.get("/api/units/feature/3").json()
    stacked = pipeline.get("/api/units/feature/4").json()

    assert gated["depends_on"] == [{"id": "feature/2", "status": "in_review"}]
    assert gated["merge_gates"] == [{"id": "feature/2", "status": "in_review"}]
    assert stacked["depends_on"] == [{"id": "feature/2", "status": "in_review"}]
    assert stacked["merge_gates"] == []


def test_the_review_round_comes_from_the_checkpointed_thread(
    inst: Installation, pipeline: httpx.Client
) -> None:
    seed_review_round(inst, "feature/2", 2)

    reviewed = pipeline.get("/api/units/feature/2").json()
    without_thread = pipeline.get("/api/units/feature/4").json()

    assert reviewed["review_round"] == 2
    assert without_thread["review_round"] is None


def test_a_unit_that_is_not_in_the_store_is_not_found(pipeline: httpx.Client) -> None:
    assert pipeline.get("/api/units/feature/99").status_code == 404
    assert pipeline.get("/api/units/nothing/1").status_code == 404
