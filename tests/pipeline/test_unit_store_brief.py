"""The focus and skippable lists stored with an approval's description."""

import json
from pathlib import Path

from agent_build_kit.pipeline.unit_store import FocusEntry, SkipEntry, UnitStore
from tests.factories import activate_with, unit
from tests.pipeline.test_stack_runner import Recorder, make_runner

UNIT_ID = unit().id


def reply(**lists: object) -> str:
    description = {"summary": "s", "changes": ["c"], **lists}
    return json.dumps({"approved": True, "feedback": "", "description": description})


def weighing(tmp_path: Path):
    activate_with(review={"enabled": True})
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    return store, make_runner(store, Recorder(), tmp_path)


def test_an_approval_stores_the_lists_and_they_round_trip(tmp_path: Path) -> None:
    store, runner = weighing(tmp_path)

    runner.weigh_review(
        unit(),
        reply(
            focus=[{"place": "src/a.py", "reason": "boundary"}],
            skippable=[{"place": "src/b.py", "reason": "renamed"}],
        ),
        judged="sha-1",
    )

    stored = UnitStore(store.path).get(UNIT_ID).description
    assert stored is not None
    assert [(e.place, e.reason) for e in stored.focus] == [("src/a.py", "boundary")]
    assert stored.skippable == (SkipEntry(place="src/b.py", reason="renamed"),)


def test_a_later_approval_replaces_them(tmp_path: Path) -> None:
    store, runner = weighing(tmp_path)
    runner.weigh_review(unit(), reply(focus=[{"place": "src/a.py", "reason": "r"}]), judged="sha-1")

    runner.weigh_review(unit(), reply(focus=[{"place": "src/c.py", "reason": "r"}]), judged="sha-2")

    stored = store.get(UNIT_ID).description
    assert stored is not None
    assert [e.place for e in stored.focus] == ["src/c.py"]
    assert stored.skippable == ()


def test_a_record_from_before_the_lists_reads_with_both_empty(tmp_path: Path) -> None:
    store, runner = weighing(tmp_path)
    runner.weigh_review(unit(), reply(), judged="sha-1")
    raw = json.loads(store.path.read_text())
    for record in raw["units"]:
        record["description"].pop("focus", None)
        record["description"].pop("skippable", None)
    store.path.write_text(json.dumps(raw))
    old = UnitStore(store.path).get(UNIT_ID).description
    assert old is not None
    assert (old.focus, old.skippable) == ((), ())

    runner.weigh_review(unit(), reply(focus=[{"place": "src/a.py", "reason": "r"}]), judged="sha-2")

    new = UnitStore(store.path).get(UNIT_ID).description
    assert new is not None
    assert new.focus == (FocusEntry(place="src/a.py", reason="r"),)
