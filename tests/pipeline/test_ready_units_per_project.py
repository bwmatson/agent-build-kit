"""The limit on units in progress applies to each project; a full one holds back its own."""

from __future__ import annotations

from agent_build_kit.pipeline.units import IN_REVIEW, Priority
from tests.factories import new_unit as new
from tests.factories import started_ids

LIMIT = 5
GATED = ({"state": "planned", "at": "2026-09-23T09:00", "cause": "gated"},)


def in_review(prefix: str, project: str, count: int):
    return [
        new(f"{prefix}{n}/1", state=IN_REVIEW, pr=1, repo="app", project=project)
        for n in range(count)
    ]


def fresh(uid: str, project: str, **kw):
    return new(uid, repo="app", project=project, **kw)


def started(graph) -> list[str]:
    return started_ids(graph, slots=9, max_units_in_progress=LIMIT)


def test_a_full_project_keeps_its_never_started_unit_planned_and_another_project_starts() -> None:
    graph = [
        *in_review("w", "web", 5),
        *in_review("p", "api", 2),
        fresh("webnew/1", "web"),
        fresh("apinew/1", "api"),
    ]

    assert started(graph) == ["apinew/1"]


def test_the_most_urgent_ready_unit_of_a_full_project_is_skipped_for_a_less_urgent_one() -> None:
    graph = [
        *in_review("w", "web", 5),
        fresh("urgent/1", "web", priority=Priority.FIX),
        fresh("later/1", "api", priority=Priority.LOW),
    ]

    assert started(graph) == ["later/1"]


def test_a_skipped_unit_takes_no_slot() -> None:
    graph = [
        *in_review("w", "web", 5),
        fresh("skipped/1", "web", priority=Priority.FIX),
        fresh("other/1", "api"),
    ]

    assert started_ids(graph, slots=1, max_units_in_progress=LIMIT) == ["other/1"]


def test_work_already_in_progress_in_a_full_project_still_starts() -> None:
    graph = [
        *in_review("w", "web", 4),
        fresh("paused/1", "web", branch="spec/paused/1"),
        fresh("fresh/1", "web"),
        fresh("apinew/1", "api"),
    ]

    assert started(graph) == ["paused/1", "apinew/1"]


def test_a_blocked_unit_that_is_unblocked_draws_on_its_own_projects_room() -> None:
    waiter = fresh("waiter/1", "web", branch="spec/waiter/1", history=GATED)
    graph = [*in_review("w", "web", 4), *in_review("p", "api", 5), waiter, fresh("new/1", "api")]

    assert started(graph) == ["waiter/1"]


def test_an_unblocked_unit_waits_when_only_another_project_has_room() -> None:
    waiter = fresh("waiter/1", "web", branch="spec/waiter/1", history=GATED)
    graph = [*in_review("w", "web", 5), waiter, fresh("new/1", "api")]

    assert started(graph) == ["new/1"]
