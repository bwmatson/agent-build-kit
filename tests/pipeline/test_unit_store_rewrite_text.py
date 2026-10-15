"""`UnitStore.rewrite_text`: one exclusive rewrite of the text fields of every record
(spec: stored-text-scrub)."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW
from tests.factories import new_unit

TEXT_FIELDS = ("feedback", "guidance", "predecessor_note", "stack_refusal")


def swap(text: str) -> str:
    return text.replace("OLD", "NEW")


def seeded(path: Path, uid: str = "add-marker/1", word: str = "OLD") -> UnitStore:
    store = UnitStore(path)
    store.upsert([new_unit(uid)])
    store.set_feedback(uid, f"{word} feedback")
    store.set_guidance(uid, f"{word} guidance")
    store.set_predecessor_note(uid, f"{word} predecessor")
    store.set_stack_refusal(uid, f"{word} refusal")
    store.set_state(uid, IN_REVIEW, note=f"{word} history")
    return store


def records(path: Path) -> list[dict]:
    return json.loads(path.read_text())["units"]


def without_text(record: dict) -> dict:
    kept = {k: v for k, v in record.items() if k not in TEXT_FIELDS}
    kept["history"] = [{k: v for k, v in e.items() if k != "note"} for e in record["history"]]
    return kept


def test_only_the_text_fields_change(tmp_path: Path) -> None:
    store = seeded(tmp_path / "units.json")
    before = records(store.path)

    changed = store.rewrite_text(swap)

    after = records(store.path)
    assert changed == ["add-marker/1"]
    for field in TEXT_FIELDS:
        assert after[0][field] == before[0][field].replace("OLD", "NEW")
    assert [e["note"] for e in after[0]["history"] if "note" in e] == ["NEW history"]
    assert without_text(after[0]) == without_text(before[0])


def test_no_match_writes_nothing_and_returns_an_empty_list(tmp_path: Path) -> None:
    store = seeded(tmp_path / "units.json", word="plain")
    os.utime(store.path, ns=(10**18, 10**18))
    before = (store.path.read_bytes(), store.path.stat().st_mtime_ns)

    changed = store.rewrite_text(swap)

    assert changed == []
    assert (store.path.read_bytes(), store.path.stat().st_mtime_ns) == before


def test_two_matching_records_are_written_once_and_a_waiting_writer_sees_both(
    tmp_path: Path,
) -> None:
    writes: list[int] = []
    store = UnitStore(tmp_path / "units.json", on_write=lambda units: writes.append(len(units)))
    seeded(store.path, "add-marker/1")
    seeded(store.path, "add-marker/2")
    store.upsert([new_unit("add-marker/3")])
    writes.clear()
    writer = threading.Thread(target=store.record_push, args=("add-marker/3", "sha-3"))

    def swap_and_start_a_writer(text: str) -> str:
        # Started under the lock, so it can only run once the rewrite has been written.
        if not writer.is_alive() and writer.ident is None:
            writer.start()
        return swap(text)

    changed = store.rewrite_text(swap_and_start_a_writer)
    writer.join()

    assert sorted(changed) == ["add-marker/1", "add-marker/2"]
    assert len(writes) == 2  # the rewrite's one write, then the waiting writer's
    final = {unit.id: unit for unit in store.all()}
    assert final["add-marker/1"].feedback == "NEW feedback"
    assert final["add-marker/2"].feedback == "NEW feedback"
    assert final["add-marker/3"].pushed == "sha-3"
