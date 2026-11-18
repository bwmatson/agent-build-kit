"""The records the resolution lanes keep, read and written from the core's `lane_records`, so the
dispatcher, `abk explain` and a worker need not import the worker's lane."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_build_kit.pipeline import host
from agent_build_kit.pipeline.lane_records import (
    clear_deferral,
    clear_worker_record,
    deferred_until,
    lane_held_by_record,
    lane_record,
    record_deferral,
    resolving_phrase,
    write_worker_record,
)
from agent_build_kit.pipeline.units import project_key
from tests.branch_lock_fakes import dead_pid
from tests.factories import stored_unit


@pytest.fixture(autouse=True)
def on_box(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(host, "this_host", lambda: "box")


@pytest.mark.parametrize(
    ("kind", "base", "phrase"),
    [
        ("comment", "main", "resolving a comment"),
        ("base", "main", "resolving base main"),
    ],
)
def test_a_resolving_phrase_names_a_comment_or_the_base(kind: str, base: str, phrase: str) -> None:
    assert resolving_phrase(kind, base) == phrase


def test_a_worker_record_holds_its_unit_while_its_process_lives_and_not_after_it_is_cleared(
    tmp_path: Path,
) -> None:
    first, second = stored_unit("c1/1"), stored_unit("c2/1")
    key = project_key(first)

    mine = write_worker_record(tmp_path, key, first, base="main")
    write_worker_record(tmp_path, key, second, base="dev", pid=os.getppid())

    assert lane_held_by_record(tmp_path) == {"c1/1", "c2/1"}
    assert {entry["unit"]: entry["base"] for entry in lane_record(tmp_path)} == {
        "c1/1": "main",
        "c2/1": "dev",
    }
    clear_worker_record(mine)
    assert lane_held_by_record(tmp_path) == {"c2/1"}


def test_a_record_whose_process_has_gone_holds_nothing(tmp_path: Path) -> None:
    unit = stored_unit("c1/1")

    write_worker_record(tmp_path, project_key(unit), unit, base="main", pid=dead_pid())

    assert lane_record(tmp_path) == []
    assert lane_held_by_record(tmp_path) == set()


def test_a_record_that_cannot_be_read_is_skipped(tmp_path: Path) -> None:
    (tmp_path / "restacks-bad.json").write_text("{not json")
    (tmp_path / "restacks-short.json").write_text(json.dumps({"pid": os.getpid()}))

    assert lane_record(tmp_path) == []


def test_a_deferral_is_read_back_until_it_is_cleared(tmp_path: Path) -> None:
    until = datetime(2030, 1, 2, 3, 4, tzinfo=UTC)
    assert deferred_until(tmp_path, "c1/1") is None

    record_deferral(tmp_path, "c1/1", until)

    assert deferred_until(tmp_path, "c1/1") == until
    assert deferred_until(tmp_path, "c2/1") is None
    clear_deferral(tmp_path, "c1/1")
    assert deferred_until(tmp_path, "c1/1") is None
