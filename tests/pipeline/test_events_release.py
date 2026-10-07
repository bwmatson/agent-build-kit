"""The hold label coming off: which units it frees, and what it loses.

A unit is held by a reviewer's label, but also by the review loop, a stack
depth cap and a toolchain that cannot build it, and none of those has anything
to do with the label. The unit records why it was held (`held_by`), and a
release frees only the first kind.
"""

import json
from functools import partial
from pathlib import Path

import pytest

from agent_build_kit.forges import PullRequest
from agent_build_kit.pipeline import events
from agent_build_kit.pipeline.labels import StateLabels
from agent_build_kit.pipeline.pr_poller import Poller
from agent_build_kit.pipeline.unit_store import Cause, HeldBy, UnitStore
from agent_build_kit.pipeline.units import HELD, IN_REVIEW, PLANNED, RUNNING, SATISFIED, UnitState
from agent_build_kit.pipeline.workspaces import branch_lock
from tests.factories import stored_unit as unit
from tests.forges.stand_in import StandInForge, lookup

UNIT = "add-marker/1"


@pytest.fixture
def store(tmp_path: Path) -> UnitStore:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(UNIT)])
    store.set_state(UNIT, IN_REVIEW, pr=1, branch="spec/add-marker/1")
    return store


@pytest.fixture
def locks(tmp_path: Path) -> Path:
    return tmp_path / "locks"


@pytest.fixture
def logged() -> list[str]:
    return []


def held_as(store: UnitStore, held_by: str | None, *, note: str = "", held_base: str = "") -> None:
    """The unit held for `held_by`, written as the record on disk would be: with
    `None`, as one stored before the cause was kept, which has no such key."""
    store.set_state(UNIT, HELD, note=note, held_base=held_base)
    raw = json.loads(store.path.read_text())
    for item in raw["units"]:
        if item["id"] == UNIT:
            if held_by is None:
                item.pop("held_by", None)
            else:
                item["held_by"] = held_by
    store.path.write_text(json.dumps(raw))


DEPTH_NOTE = events.DEPTH_HOLD.format(new_base="main", depth=3, cap=2) + (
    events.DEPTH_HOLD_BASE.format(old_base="spec/c/1")
)


def release(store: UnitStore, logged: list[str], **kwargs) -> bool:
    return events.on_release(1, repo="app", store=store, log=logged.append, **kwargs)


# --- the cause of a hold is recorded ---------------------------------------------------


def test_the_hold_label_records_that_a_reviewer_held_the_unit(store: UnitStore) -> None:
    events.on_hold(1, repo="app", store=store, log=lambda m: None)

    stored = store.get(UNIT)
    assert stored.state == HELD
    assert stored.held_by == "reviewer"


def test_the_hold_label_records_the_reviewer_hold_cause(store: UnitStore) -> None:
    events.on_hold(1, repo="app", store=store, log=lambda m: None)

    assert store.get(UNIT).cause == Cause.REVIEWER_HOLD


def test_a_unit_leaving_held_forgets_why_it_was_held(store: UnitStore) -> None:
    events.on_hold(1, repo="app", store=store, log=lambda m: None)
    assert store.get(UNIT).held_by == "reviewer"

    store.set_state(UNIT, PLANNED, note="requeued")

    assert store.get(UNIT).held_by == ""


def test_the_hold_label_notes_that_a_reviewer_held_the_unit(store: UnitStore) -> None:
    events.on_hold(1, repo="app", store=store, log=lambda m: None)

    assert store.get(UNIT).note == "held by a reviewer"


def test_a_replan_keeps_the_label_hold_and_its_release_still_applies(
    store: UnitStore, logged: list[str]
) -> None:
    events.on_hold(1, repo="app", store=store, log=lambda m: None)

    store.upsert([unit(UNIT)])

    assert store.get(UNIT).held_by == "reviewer"
    release(store, logged)
    assert store.get(UNIT).state == IN_REVIEW


def test_a_replan_keeps_a_depth_hold(store: UnitStore) -> None:
    store.set_state(UNIT, HELD, note="too deep", held_by=HeldBy.DEPTH)

    store.upsert([unit(UNIT)])

    assert store.get(UNIT).state == HELD
    assert store.get(UNIT).held_by == "depth"


def test_a_hold_on_a_unit_with_a_thread_names_the_cause_it_really_has(
    store: UnitStore, logged: list[str]
) -> None:
    store.set_state(UNIT, HELD, note="rounds spent", held_by=HeldBy.REVIEW)

    events.on_hold(1, repo="app", store=store, resume=lambda *a: True, log=logged.append)

    assert any("already held by review" in line for line in logged)
    assert not any("the pipeline will not touch it" in line for line in logged)


def test_a_hold_on_a_depth_held_unit_with_a_thread_says_the_label_has_it(
    store: UnitStore, logged: list[str]
) -> None:
    store.set_state(UNIT, HELD, note="too deep", held_by=HeldBy.DEPTH)

    events.on_hold(1, repo="app", store=store, resume=lambda *a: True, log=logged.append)

    assert not any("already held by" in line for line in logged)
    assert any("the pipeline will not touch it" in line for line in logged)


def test_a_stored_unit_with_no_recorded_cause_still_loads(store: UnitStore) -> None:
    held_as(store, None)

    assert store.get(UNIT).held_by == ""


# --- a hold the label caused is released -----------------------------------------------


def test_a_unit_the_label_held_goes_back_to_waiting_for_review(
    store: UnitStore, logged: list[str]
) -> None:
    events.on_hold(1, repo="app", store=store, log=lambda m: None)

    handled = release(store, logged)

    assert handled
    stored = store.get(UNIT)
    assert stored.state == IN_REVIEW
    assert stored.held_by == ""
    assert any("#1" in line and "release" in line.lower() for line in logged)


def test_a_release_resumes_the_units_thread_with_a_release_event(
    store: UnitStore, logged: list[str]
) -> None:
    events.on_hold(1, repo="app", store=store, log=lambda m: None)
    delivered: list[tuple[str, str]] = []

    def resume(stored, kind: str, reason: str, feedback, **kwargs) -> bool:
        delivered.append((stored.id, kind))
        return True

    handled = release(store, logged, resume=resume)

    assert handled
    assert delivered == [(UNIT, "release")]
    assert any("#1" in line and "release" in line.lower() for line in logged)


def test_a_stored_unit_whose_last_note_says_a_reviewer_held_it_is_not_released_by_the_note(
    store: UnitStore, logged: list[str]
) -> None:
    """What the label handler wrote before the cause was kept: no code reads it now."""
    held_as(store, None, note="held by a reviewer")

    release(store, logged)

    assert store.get(UNIT).state == HELD


def test_a_stored_unit_with_no_cause_and_no_such_note_stays_held(
    store: UnitStore, logged: list[str]
) -> None:
    held_as(store, None, note="rounds spent with work outstanding: rename the flag")

    release(store, logged)

    assert store.get(UNIT).state == HELD
    assert any("not the label's" in line for line in logged)


# --- a hold the label did not cause stays ----------------------------------------------


@pytest.mark.parametrize("cause", ["review", "depth", "toolchain"])
def test_a_hold_the_label_did_not_cause_stays_and_the_log_says_so(
    store: UnitStore, logged: list[str], cause: str
) -> None:
    held_as(store, cause, note="held by a reviewer")
    resumed: list[str] = []

    handled = release(store, logged, resume=lambda *a, **k: resumed.append("called") or True)

    assert handled, "handled, so the poller does not keep reporting it"
    assert resumed == [], "the thread is not woken"
    stored = store.get(UNIT)
    assert (stored.state, stored.held_by) == (HELD, cause)
    assert any("#1" in line and "not the label's" in line for line in logged)


# --- nothing to release ----------------------------------------------------------------


def test_a_release_for_a_pr_with_no_unit_is_ignored(store: UnitStore, logged: list[str]) -> None:
    handled = events.on_release(99, repo="app", store=store, log=logged.append)

    assert handled
    assert store.get(UNIT).state == IN_REVIEW
    assert any("#99" in line for line in logged)


def test_a_release_for_a_unit_in_another_repo_is_ignored(
    store: UnitStore, logged: list[str]
) -> None:
    held_as(store, "reviewer")

    handled = events.on_release(1, repo="platform", store=store, log=logged.append)

    assert handled
    assert store.get(UNIT).state == HELD


@pytest.mark.parametrize("state", [IN_REVIEW, SATISFIED])
def test_a_release_for_a_unit_that_is_not_held_changes_nothing(
    store: UnitStore, logged: list[str], state: UnitState
) -> None:
    store.set_state(UNIT, state)
    before = store.history(UNIT)

    handled = release(store, logged)

    assert handled
    assert store.get(UNIT).state == state
    assert store.history(UNIT) == before


# --- a unit being built defers it ------------------------------------------------------


@pytest.mark.parametrize("state", [HELD, RUNNING])
def test_a_release_for_a_unit_being_built_is_deferred(
    store: UnitStore, locks: Path, logged: list[str], state: UnitState
) -> None:
    held_as(store, "reviewer")
    if state != HELD:
        store.set_state(UNIT, state)

    with branch_lock("spec/add-marker/1", root=locks):
        handled = release(store, logged, claim=events.build_claim(locks))

    assert handled is False, "deferred, so the poller reports it again"
    assert store.get(UNIT).state == state


# --- the pull request's state label ----------------------------------------------------


def test_the_state_label_returns_to_in_review(tmp_path: Path) -> None:
    forge = StandInForge()
    labels = StateLabels(lookup(forge), log=lambda m: None)
    store = UnitStore(
        tmp_path / "units.json",
        on_state=lambda stored, every, opened: labels.follow(stored, every, opened=opened),
    )
    store.upsert([unit(UNIT)])
    store.set_state(UNIT, IN_REVIEW, pr=1, branch="spec/add-marker/1")
    events.on_hold(1, repo="app", store=store, log=lambda m: None)
    assert forge.on_pr[1] & {"held", "in-review"} == {"held"}

    events.on_release(1, repo="app", store=store, log=lambda m: None)

    assert forge.on_pr[1] & {"held", "in-review"} == {"in-review"}


# --- through the poller: nothing that happened during the hold is lost -----------------


def pull(**overrides) -> PullRequest:
    fields: dict = {"number": 1, "head": "spec/add-marker/1", "base": "main", "state": "open"}
    return PullRequest(**{**fields, **overrides})


def poller_over(tmp_path: Path, store: UnitStore, locks: Path, pages: list[PullRequest]) -> Poller:
    queue = iter(pages)
    return Poller(
        repo="example/app",
        state_path=tmp_path / "prs-app.json",
        list_prs=lambda: [next(queue)],
        dispatch=partial(
            events.build_dispatch(
                store,
                restack=lambda **kw: None,
                claim=events.build_claim(locks),
                log=lambda m: None,
            ),
            repo="app",
        ),
    )


HOLD = ("agent-hold",)


def test_removing_the_label_returns_a_held_unit_to_review(
    tmp_path: Path, store: UnitStore, locks: Path
) -> None:
    poller = poller_over(tmp_path, store, locks, [pull(), pull(labels=HOLD), pull()])
    poller.poll()
    poller.poll()
    assert store.get(UNIT).state == HELD

    poller.poll()

    assert store.get(UNIT).state == IN_REVIEW


def test_a_comment_left_during_the_hold_is_delivered_after_the_release(
    tmp_path: Path, store: UnitStore, locks: Path
) -> None:
    commented = {"conversation": ("c1",), "comment_bodies": ("rename the flag",)}
    poller = poller_over(
        tmp_path,
        store,
        locks,
        [
            pull(),
            pull(labels=HOLD),
            pull(labels=HOLD, **commented),
            pull(**commented),
            pull(**commented),
        ],
    )
    for _ in range(4):
        poller.poll()
    assert store.get(UNIT).state == IN_REVIEW

    poller.poll()

    stored = store.get(UNIT)
    assert stored.state == PLANNED
    assert "rename the flag" in stored.feedback


def test_a_failing_check_during_the_hold_is_delivered_after_the_release(
    tmp_path: Path, store: UnitStore, locks: Path
) -> None:
    poller = poller_over(
        tmp_path,
        store,
        locks,
        [
            pull(),
            pull(labels=HOLD),
            pull(labels=HOLD, failing_checks=("CI",)),
            pull(failing_checks=("CI",)),
            pull(failing_checks=("CI",)),
        ],
    )
    for _ in range(4):
        poller.poll()
    assert store.get(UNIT).state == IN_REVIEW

    poller.poll()

    stored = store.get(UNIT)
    assert stored.state == PLANNED
    assert "CI" in stored.feedback


def test_a_comment_already_seen_under_the_hold_is_not_delivered_twice(
    tmp_path: Path, store: UnitStore, locks: Path
) -> None:
    """The unit is not held when a comment arrives and is reworked for it; the
    hold, and its release, that follow find nothing new."""
    commented = {"conversation": ("c1",), "comment_bodies": ("rename the flag",)}
    poller = poller_over(
        tmp_path,
        store,
        locks,
        [pull(), pull(**commented), pull(labels=HOLD, **commented), pull(**commented)] * 2,
    )
    poller.poll()
    poller.poll()
    assert store.get(UNIT).state == PLANNED
    store.set_state(UNIT, IN_REVIEW)

    poller.poll()
    poller.poll()

    assert store.get(UNIT).state == IN_REVIEW


def test_a_release_for_a_unit_being_built_is_reported_again_by_a_later_poll(
    tmp_path: Path, store: UnitStore, locks: Path
) -> None:
    poller = poller_over(tmp_path, store, locks, [pull(), pull(labels=HOLD), pull(), pull()])
    poller.poll()
    poller.poll()
    assert store.get(UNIT).state == HELD

    with branch_lock("spec/add-marker/1", root=locks):
        poller.poll()
    assert store.get(UNIT).state == HELD

    poller.poll()

    assert store.get(UNIT).state == IN_REVIEW


def test_a_comment_already_answered_is_not_delivered_again_after_the_release(
    tmp_path: Path, store: UnitStore, locks: Path
) -> None:
    commented = {"conversation": ("c1",), "comment_bodies": ("rename the flag",)}
    poller = poller_over(
        tmp_path,
        store,
        locks,
        [pull(), pull(**commented), pull(labels=HOLD, **commented), pull(**commented)]
        + [pull(**commented)],
    )
    poller.poll()
    poller.poll()
    store.set_state(UNIT, IN_REVIEW)
    feedback = store.get(UNIT).feedback
    poller.poll()
    poller.poll()
    assert store.get(UNIT).state == IN_REVIEW

    poller.poll()

    stored = store.get(UNIT)
    assert stored.state == IN_REVIEW
    assert stored.feedback == feedback


# --- a hold the label did not make is not the label's to release -----------------------


@pytest.mark.parametrize(
    ("cause", "note"),
    [
        ("review", "rounds spent with work outstanding: rename the flag"),
        ("toolchain", "the toolchain cannot build it"),
        (None, "rounds spent with work outstanding: rename the flag"),
    ],
    ids=["review", "toolchain", "unrecorded"],
)
def test_the_label_added_and_removed_leaves_another_cause_of_the_hold_alone(
    store: UnitStore, logged: list[str], cause: str | None, note: str
) -> None:
    held_as(store, cause, note=note)
    before = store.history(UNIT)

    events.on_hold(1, repo="app", store=store, log=logged.append)
    release(store, logged)

    stored = store.get(UNIT)
    assert stored.state == HELD
    assert stored.held_by == (cause or "")
    assert store.history(UNIT) == before, "neither event wrote the record"
    assert any("already held by" in line for line in logged)


def test_the_label_takes_over_a_depth_hold_and_its_removal_gives_it_back(
    store: UnitStore, logged: list[str]
) -> None:
    held_as(store, HeldBy.DEPTH, note=DEPTH_NOTE, held_base="spec/c/1")

    events.on_hold(1, repo="app", store=store, log=logged.append)

    stored = store.get(UNIT)
    assert (stored.state, stored.held_by) == (HELD, "reviewer")
    assert stored.held_base == "spec/c/1", "what the depth hold needs is kept"

    release(store, logged)

    stored = store.get(UNIT)
    assert (stored.state, stored.held_by) == (HELD, "depth")
    assert stored.held_base == "spec/c/1"
    assert events.held_for_depth(stored)


def test_a_depth_hold_with_no_recorded_base_is_not_given_back_from_its_note(
    store: UnitStore, logged: list[str]
) -> None:
    """A hold from before the base was a field: the note carries it, and is not read."""
    held_as(store, HeldBy.DEPTH, note=DEPTH_NOTE)
    events.on_hold(1, repo="app", store=store, log=logged.append)

    release(store, logged)

    assert store.get(UNIT).held_by != "depth"


def test_a_unit_stored_running_with_nothing_building_it_is_not_released(
    store: UnitStore, locks: Path, logged: list[str]
) -> None:
    """Both events were deferred while it built; the build died. Under the claim
    `running` no longer means being built, and the unit was never held."""
    store.set_state(UNIT, RUNNING)
    before = store.history(UNIT)

    handled = release(store, logged, claim=events.build_claim(locks))

    assert handled
    assert store.get(UNIT).state == RUNNING
    assert store.history(UNIT) == before


@pytest.mark.parametrize(
    "arrival",
    [{"mergeable": False}, {"review_decision": "changes_requested"}, {"labels": ("agent-rework",)}],
    ids=["conflict", "changes-requested", "rework-label"],
)
def test_what_arrived_during_the_hold_is_reworked_once_the_unit_is_released(
    tmp_path: Path, store: UnitStore, locks: Path, arrival: dict
) -> None:
    held = {**arrival, "labels": (*HOLD, *arrival.get("labels", ()))}
    released = {**arrival, "labels": arrival.get("labels", ())}
    poller = poller_over(
        tmp_path,
        store,
        locks,
        [pull(mergeable=True), pull(labels=HOLD, mergeable=True), pull(**held), pull(**released)]
        + [pull(**released)],
    )
    for _ in range(4):
        poller.poll()
    assert store.get(UNIT).state == IN_REVIEW

    poller.poll()

    assert store.get(UNIT).state == PLANNED


def test_a_conflict_arriving_with_the_label_is_reworked_once_the_unit_is_released(
    tmp_path: Path, store: UnitStore, locks: Path
) -> None:
    poller = poller_over(
        tmp_path,
        store,
        locks,
        [
            pull(mergeable=True),
            pull(labels=HOLD, mergeable=False),
            pull(mergeable=False),
            pull(mergeable=False),
        ],
    )
    for _ in range(3):
        poller.poll()
    assert store.get(UNIT).state == IN_REVIEW

    poller.poll()

    assert store.get(UNIT).state == PLANNED


def test_a_cancelled_check_first_seen_under_the_hold_is_rerun_once_after_the_release(
    tmp_path: Path, store: UnitStore, locks: Path
) -> None:
    store.record_push(UNIT, "aaa1111")
    cancelled = {"cancelled_checks": ("CI",)}
    queue = iter(
        [
            pull(),
            pull(labels=HOLD),
            pull(labels=HOLD, **cancelled),
            pull(**cancelled),
            pull(**cancelled),
        ]
    )
    reran: list[str] = []

    def rerun(repo: str, pull: PullRequest) -> None:
        reran.append(store.get(UNIT).state)

    poller = Poller(
        repo="example/app",
        state_path=tmp_path / "prs-app.json",
        list_prs=lambda: [next(queue)],
        dispatch=partial(
            events.build_dispatch(
                store,
                restack=lambda **kw: None,
                rerun_checks=rerun,
                claim=events.build_claim(locks),
                log=lambda m: None,
            ),
            repo="app",
        ),
    )
    for _ in range(4):
        poller.poll()
    assert reran == []

    poller.poll()

    assert reran == [IN_REVIEW]
