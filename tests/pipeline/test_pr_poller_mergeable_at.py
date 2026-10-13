"""The snapshot says when its mergeability answer was read, and since when it conflicts.

A conflict that stands is only worth acting on if the answer is newer than the
unit's own push, so the poll records the time of each definite answer.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from tests.fake_clock import START
from tests.pr_poller_fakes import PollerRig, in_review_unit


@pytest.fixture
def rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> PollerRig:
    return PollerRig(tmp_path, monkeypatch, in_review_unit())


def at(value: str) -> datetime:
    return datetime.fromisoformat(value)


def test_a_definite_answer_is_recorded_with_the_time_of_the_poll_that_read_it(
    rig: PollerRig,
) -> None:
    rig.poll(True)
    rig.poll(False)

    assert at(rig.seen()["mergeable_at"]) == START + timedelta(seconds=600)


def test_an_undetermined_answer_keeps_the_last_definite_value_and_its_time(
    rig: PollerRig,
) -> None:
    rig.poll(False)
    rig.poll(False)
    rig.poll(None)

    seen = rig.seen()
    assert seen["mergeable"] is False
    assert at(seen["mergeable_at"]) == START + timedelta(seconds=600)
    assert at(seen["conflict_since"]) == START + timedelta(seconds=300)


def test_a_snapshot_recorded_before_the_time_was_kept_is_never_fresh(
    rig: PollerRig,
) -> None:
    rig.path.write_text(json.dumps({"4": {"state": "open", "mergeable": False}}))
    rig.push(ago=3600)

    rig.poll(None)
    assert rig.seen().get("mergeable_at") is None
    assert rig.names() == []

    rig.poll(False)
    assert rig.names() == ["conflict"]


def test_a_mergeable_answer_clears_the_start_of_the_conflict(rig: PollerRig) -> None:
    rig.poll(False)
    rig.poll(False)

    rig.poll(True)

    seen = rig.seen()
    assert seen["conflict_since"] is None
    assert at(seen["mergeable_at"]) == START + timedelta(seconds=900)


def test_a_conflict_after_a_mergeable_answer_starts_a_new_one(rig: PollerRig) -> None:
    rig.poll(False)
    rig.poll(True)

    rig.poll(False)

    assert at(rig.seen()["conflict_since"]) == START + timedelta(seconds=900)
