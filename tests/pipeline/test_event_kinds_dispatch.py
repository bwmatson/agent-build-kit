"""The poller names what sent a unit back, the dispatch hands that on, and the rework
takes its feedback from it; no handler parses the reason's text."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_build_kit.forges import PullRequest
from agent_build_kit.pipeline import events
from agent_build_kit.pipeline.pr_poller import REWORK_LABEL, Poller, snapshot
from agent_build_kit.pipeline.unit_store import FeedbackSource, ReworkKind, UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, PLANNED
from tests.check_lists import failed_list
from tests.factories import stored_unit as unit

UNIT = "add-marker/1"


def pr(number: int = 4, **overrides) -> PullRequest:
    defaults: dict = {
        "number": number,
        "head": "spec/add-marker/1",
        "base": "main",
        "state": "open",
    }
    return PullRequest(**{**defaults, **overrides})


def polled(tmp_path: Path, before: PullRequest | None, now: PullRequest) -> list[dict]:
    """The keyword arguments of each rework one poll dispatches."""
    state = tmp_path / "prs.json"
    state.write_text(json.dumps({} if before is None else {str(before.number): snapshot(before)}))
    seen: list[dict] = []
    Poller(
        repo="o/r",
        state_path=state,
        dispatch=lambda event, number, **kwargs: seen.append({"event": event, **kwargs}),
        list_prs=lambda: [now],
    ).poll()
    return [call for call in seen if call["event"] == "rework"]


@pytest.mark.parametrize(
    ("before", "now", "kind"),
    [
        (None, pr(checks=failed_list("CI")), ReworkKind.FAILING_CHECKS),
        (pr(), pr(checks=failed_list("CI")), ReworkKind.FAILING_CHECKS),
        (None, pr(mergeable=False), ReworkKind.CONFLICT),
        (pr(mergeable=True), pr(mergeable=False), ReworkKind.CONFLICT),
        (pr(), pr(labels=(REWORK_LABEL,)), ReworkKind.LABEL),
        (pr(), pr(review_decision="changes_requested"), ReworkKind.CHANGES_REQUESTED),
        (pr(), pr(conversation=("c1",), comment_bodies=("thoughts?",)), ReworkKind.COMMENT),
    ],
)
def test_each_poller_event_names_its_rework_kind(
    tmp_path: Path, before: PullRequest | None, now: PullRequest, kind: ReworkKind
) -> None:
    (call,) = polled(tmp_path, before, now)

    assert call["rework"] is kind


@pytest.fixture
def store(tmp_path: Path) -> UnitStore:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(UNIT)])
    store.set_state(UNIT, IN_REVIEW, pr=1, branch="spec/add-marker/1")
    return store


def review_of(*lines: str):
    return lambda number: events.Review(lines=list(lines), ids=("n1",))


def log_of(text: str):
    return lambda pull: text


def rework(store: UnitStore, kind: ReworkKind, reason: str) -> None:
    events.on_rework(
        1,
        repo="app",
        reason=reason,
        rework=kind,
        pull=pr(1),
        store=store,
        fetch_review=review_of("src/app.py:3 — use a Sequence"),
        fetch_checks=log_of("FAILED tests/test_app.py::test_marker"),
    )


def test_the_dispatch_hands_the_kind_to_the_thread(store: UnitStore) -> None:
    delivered: list[dict] = []

    def resume(unit, kind, reason, feedback, **kwargs) -> bool:
        delivered.append({"kind": kind, **kwargs})
        return True

    dispatch = events.build_dispatch(store, restack=lambda **kwargs: None, resume=resume)

    dispatch(
        "rework", 1, repo="app", pull=pr(1), reason="words", rework=ReworkKind.CHANGES_REQUESTED
    )

    assert delivered == [{"kind": "rework", "rework": ReworkKind.CHANGES_REQUESTED}]


def test_failing_checks_get_the_ci_log_only_whatever_the_reason_says(store: UnitStore) -> None:
    rework(store, ReworkKind.FAILING_CHECKS, "something went red")

    stored = store.get(UNIT)
    assert "FAILED tests/test_app.py::test_marker" in stored.feedback
    assert "use a Sequence" not in stored.feedback
    assert stored.feedback_source == FeedbackSource.CI
    assert not stored.feedback_from_person
    assert stored.state == PLANNED


def test_a_conflict_gets_the_restack_instructions_whatever_the_reason_says(
    store: UnitStore,
) -> None:
    rework(store, ReworkKind.CONFLICT, "the branch does not merge")

    stored = store.get(UNIT)
    assert "do not rebase or reset" in stored.feedback
    assert "use a Sequence" not in stored.feedback
    assert stored.feedback_source == FeedbackSource.CONFLICT


@pytest.mark.parametrize(
    "kind", [ReworkKind.LABEL, ReworkKind.CHANGES_REQUESTED, ReworkKind.COMMENT]
)
def test_the_other_kinds_get_the_reviewer_s_words_even_when_the_reason_reads_like_a_check(
    store: UnitStore, kind: ReworkKind
) -> None:
    rework(store, kind, "failing checks: CI")

    stored = store.get(UNIT)
    assert "use a Sequence" in stored.feedback
    assert "FAILED tests/test_app.py" not in stored.feedback
    assert stored.feedback_source == FeedbackSource.REVIEW
    assert stored.feedback_from_person
