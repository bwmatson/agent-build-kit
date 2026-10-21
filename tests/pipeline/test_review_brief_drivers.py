"""A unit's recorded drivers lead its focus list (spec: review-brief)."""

import json
from pathlib import Path

import pytest

from agent_build_kit.pipeline.unit_store import Description, UnitStore
from tests.factories import activate_with, unit
from tests.pipeline.test_stack_runner import Recorder, make_runner

UNIT_ID = unit().id


@pytest.fixture(autouse=True)
def review_enabled() -> None:
    activate_with(review={"enabled": True})


def reply(*, focus: list[dict], skippable: list[dict] | None = None, **fields: object) -> str:
    description = {"summary": "s", "changes": ["c"], "focus": focus, "skippable": skippable or []}
    return json.dumps({"approved": True, "feedback": "", "description": description, **fields})


def stored(tmp_path: Path, raw: str) -> Description:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    make_runner(store, Recorder(), tmp_path).weigh_review(unit(), raw, judged="sha-1")
    description = UnitStore(store.path).get(UNIT_ID).description
    assert description is not None
    return description


def stored_focus(tmp_path: Path, raw: str) -> list[tuple[str, str]]:
    return [(entry.place, entry.reason) for entry in stored(tmp_path, raw).focus]


def test_drivers_lead_in_their_recorded_order_and_the_reviewers_entries_follow(
    tmp_path: Path,
) -> None:
    raw = reply(
        focus=[{"place": "src/c.py", "reason": "behaviour change"}],
        classification="light",
        drivers=["src/a.py", "src/b.py"],
    )

    places = [place for place, _ in stored_focus(tmp_path, raw)]

    assert places == ["src/a.py", "src/b.py", "src/c.py"]


def test_a_place_named_as_a_driver_and_by_the_reviewer_appears_once_with_the_reviewers_reason(
    tmp_path: Path,
) -> None:
    raw = reply(
        focus=[
            {"place": "src/other.py", "reason": "hard to undo"},
            {"place": "src/events.py", "reason": "boundary"},
        ],
        classification="full",
        drivers=["src/events.py"],
    )

    assert stored_focus(tmp_path, raw) == [
        ("src/events.py", "boundary"),
        ("src/other.py", "hard to undo"),
    ]


def test_a_unit_with_no_drivers_gets_the_reviewers_list_unchanged(tmp_path: Path) -> None:
    raw = reply(
        focus=[
            {"place": "src/x.py", "reason": "boundary"},
            {"place": "src/y.py", "reason": "hard to undo"},
        ],
        classification="auto",
    )

    assert stored_focus(tmp_path, raw) == [("src/x.py", "boundary"), ("src/y.py", "hard to undo")]


def test_a_unit_with_no_recorded_classification_gets_the_reviewers_list_unchanged(
    tmp_path: Path,
) -> None:
    activate_with(review={"enabled": False})
    raw = reply(focus=[{"place": "src/x.py", "reason": "boundary"}], drivers=["src/d.py"])

    assert stored_focus(tmp_path, raw) == [("src/x.py", "boundary")]


def test_a_driver_the_reviewer_listed_as_skippable_is_in_focus_only(tmp_path: Path) -> None:
    raw = reply(
        focus=[],
        skippable=[
            {"place": "src/a.py", "reason": "renamed"},
            {"place": "src/b.py", "reason": "moved"},
        ],
        classification="light",
        drivers=["src/a.py"],
    )

    description = stored(tmp_path, raw)

    assert [entry.place for entry in description.focus] == ["src/a.py"]
    assert [entry.place for entry in description.skippable] == ["src/b.py"]


def test_a_focus_list_naming_one_place_twice_is_stored_once(tmp_path: Path) -> None:
    raw = reply(
        focus=[
            {"place": "src/a.py", "reason": "boundary"},
            {"place": "src/a.py", "reason": "hard to undo"},
        ],
        classification="auto",
    )

    assert stored_focus(tmp_path, raw) == [("src/a.py", "boundary")]
