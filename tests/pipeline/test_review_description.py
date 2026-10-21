"""The reviewer describes the branch when it approves.

The reviewer is faked at its boundary: the raw JSON reply the review run
returns, which the loop parses. An approving verdict may carry a description
(a summary and core changes); it is stored with the approval, replaced by a
later approval, and a malformed one is ignored without costing the approval.
"""

import json
from pathlib import Path

import pytest

from agent_build_kit.pipeline.stack_runner import parse_verdict
from agent_build_kit.pipeline.unit_store import Description, UnitStore
from agent_build_kit.pipeline.wiring import REVIEW_PROMPT
from tests.factories import unit
from tests.pipeline.test_stack_runner import Recorder, make_runner

FIRST = Description(
    summary="Registers the marker at startup.",
    changes=("The marker registry exists.", "Startup registers each marker."),
)
SECOND = Description(summary="Registers markers lazily.", changes=("Markers register on use.",))


def _reply(approved: bool = True, **fields: object) -> str:
    return json.dumps({"approved": approved, "feedback": "", **fields})


def _described(description: Description) -> str:
    return _reply(description=description.model_dump(mode="json"))


def _weighing(tmp_path: Path):
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    return store, make_runner(store, Recorder(), tmp_path)


# 2.1 — the verdict parser


def test_an_approval_with_a_description_is_read_with_it() -> None:
    verdict = parse_verdict(_described(FIRST))

    assert verdict.approved is True
    assert verdict.description == FIRST


def test_a_verdict_without_a_description_has_none() -> None:
    assert parse_verdict(_reply()).description is None


@pytest.mark.parametrize(
    "malformed",
    [
        "just a sentence",
        ["a", "b"],
        {"summary": "s", "changes": "not a list"},
        {"summary": {"nested": 1}, "changes": []},
        {"summary": "s", "changes": [1, 2]},
        {"summary": "", "changes": []},
        {"summary": ""},
        {"summary": "x", "changes": []},
        {"changes": ["", " "]},
    ],
    ids=[
        "string",
        "list",
        "changes-string",
        "summary-object",
        "changes-numbers",
        "empty",
        "empty-summary-only",
        "summary-without-changes",
        "blank-changes",
    ],
)
def test_a_malformed_description_is_ignored_and_the_approval_stands(malformed: object) -> None:
    verdict = parse_verdict(_reply(description=malformed))

    assert verdict.approved is True
    assert verdict.description is None


# 2.2 — what is stored


def test_an_approval_stores_the_description_with_the_approved_commit(tmp_path: Path) -> None:
    store, runner = _weighing(tmp_path)

    weighed = runner.weigh_review(unit(), _described(FIRST), judged="sha-1")

    assert weighed.approved is True
    stored = store.get(unit().id)
    assert (stored.approved, stored.description) == ("sha-1", FIRST)


def test_a_later_approval_replaces_the_description(tmp_path: Path) -> None:
    store, runner = _weighing(tmp_path)
    runner.weigh_review(unit(), _described(FIRST), judged="sha-1")

    runner.weigh_review(unit(), _described(SECOND), judged="sha-2")

    stored = store.get(unit().id)
    assert (stored.approved, stored.description) == ("sha-2", SECOND)


def test_a_rework_that_is_not_approved_leaves_the_stored_description(tmp_path: Path) -> None:
    store, runner = _weighing(tmp_path)
    runner.weigh_review(unit(), _described(FIRST), judged="sha-1")

    weighed = runner.weigh_review(
        unit(), _reply(approved=False, feedback="rename it"), judged="sha-2"
    )

    assert weighed.approved is False
    stored = store.get(unit().id)
    assert (stored.approved, stored.description) == ("sha-1", FIRST)


def test_an_empty_description_leaves_the_earlier_one_stored(tmp_path: Path) -> None:
    store, runner = _weighing(tmp_path)
    runner.weigh_review(unit(), _described(FIRST), judged="sha-1")

    runner.weigh_review(unit(), _reply(description={"summary": "", "changes": []}), judged="sha-2")

    stored = store.get(unit().id)
    assert (stored.approved, stored.description) == ("sha-2", FIRST)


def test_a_summary_with_no_changes_leaves_the_earlier_description_stored(tmp_path: Path) -> None:
    store, runner = _weighing(tmp_path)
    runner.weigh_review(unit(), _described(FIRST), judged="sha-1")

    runner.weigh_review(unit(), _reply(description={"summary": "x", "changes": []}), judged="sha-2")

    stored = store.get(unit().id)
    assert (stored.approved, stored.description) == ("sha-2", FIRST)


def test_blank_changes_are_dropped_from_a_description() -> None:
    verdict = parse_verdict(_reply(description={"summary": " s ", "changes": ["", " a ", "  "]}))

    assert verdict.description == Description(summary="s", changes=("a",))


def test_a_malformed_description_leaves_the_approval_standing(tmp_path: Path) -> None:
    store, runner = _weighing(tmp_path)

    weighed = runner.weigh_review(unit(), _reply(description="oops"), judged="sha-1")

    assert weighed.approved is True
    stored = store.get(unit().id)
    assert (stored.approved, stored.description) == ("sha-1", None)


def test_a_record_with_no_description_loads_with_none_and_is_written_without_it(
    tmp_path: Path,
) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    store.record_approval(unit().id, "sha-1")

    assert store.get(unit().id).description is None
    written = json.loads(store.path.read_text())["units"][0]
    assert "description" not in written


def test_a_stored_description_round_trips(tmp_path: Path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    store.record_approval(unit().id, "sha-1", FIRST)

    written = json.loads(store.path.read_text())["units"][0]
    assert written["description"] == {
        "summary": FIRST.summary,
        "changes": list(FIRST.changes),
        "focus": [],
        "skippable": [],
    }
    assert UnitStore(store.path).get(unit().id).description == FIRST


# 2.4 — the reviewer's prompt


def test_the_reviewer_is_asked_for_a_description_from_the_diff() -> None:
    prompt = " ".join(REVIEW_PROMPT.split())

    assert '"description"' in prompt
    assert '"summary"' in prompt
    assert '"changes"' in prompt
    assert "not seen the spec" in prompt or "not read the spec" in prompt
    assert "diff" in prompt
