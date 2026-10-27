"""A lease records its host, and a lease of another host is never judged by this one's /proc."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_build_kit.pipeline import host
from agent_build_kit.pipeline.lease import Leases, lease_dir

UNIT = "feature/2"
GONE = {"pid": 2**22 + 99, "started": "1"}


@pytest.fixture(autouse=True)
def on_box(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(host, "this_host", lambda: "box")


def lease_file(tmp_path: Path) -> Path:
    return lease_dir(tmp_path) / "feature--2.lease"


def leases(tmp_path: Path) -> Leases:
    return Leases(lease_dir(tmp_path))


def rewrite(tmp_path: Path, **fields: object) -> None:
    """The lease on disk with `fields` set; a field set to None is removed."""
    path = lease_file(tmp_path)
    record = {**json.loads(path.read_text()), **fields}
    path.write_text(json.dumps({k: v for k, v in record.items() if v is not None}))


def foreign(tmp_path: Path) -> Leases:
    """A lease taken, then recorded as one of host `other` by a process that is not here."""
    held = leases(tmp_path)
    held.take(UNIT, "tab:a")
    rewrite(tmp_path, host="other", **GONE)
    return held


def test_a_lease_records_the_host_it_was_taken_on(tmp_path: Path) -> None:
    leases(tmp_path).take(UNIT, "tab:a")

    assert json.loads(lease_file(tmp_path).read_text())["host"] == "box"


def test_a_lease_without_a_host_is_judged_by_the_process_table(tmp_path: Path) -> None:
    held = leases(tmp_path)
    held.take(UNIT, "tab:a")
    assert json.loads(lease_file(tmp_path).read_text())["host"] == "box"
    rewrite(tmp_path, host=None)

    assert held.holder(UNIT) == "tab:a"
    rewrite(tmp_path, **GONE)
    assert held.holder(UNIT) is None


def test_a_lease_of_another_host_is_live_and_refuses_a_second_holder(tmp_path: Path) -> None:
    held = foreign(tmp_path)

    assert held.take(UNIT, "tab:b") is False
    seen = held.attachment(UNIT)
    assert seen is not None
    assert seen.host == "other"
    assert seen.stale is False
    assert held.holder(UNIT) == "tab:a"


def test_release_all_and_hand_over_leave_a_lease_of_another_host(tmp_path: Path) -> None:
    held = foreign(tmp_path)

    held.release_all("tab:a")
    held.hand_over(UNIT, "tab:a", "tab:c")

    assert json.loads(lease_file(tmp_path).read_text())["holder"] == "tab:a"
    assert held.holder(UNIT) == "tab:a"


def test_drop_removes_a_lease_of_another_host(tmp_path: Path) -> None:
    held = foreign(tmp_path)
    assert held.holder(UNIT) == "tab:a"

    held.drop(UNIT)

    assert not lease_file(tmp_path).exists()


def test_the_same_holder_name_does_not_take_over_a_lease_of_another_host(tmp_path: Path) -> None:
    held = foreign(tmp_path)
    before = lease_file(tmp_path).read_text()

    assert held.take(UNIT, "tab:a") is False

    assert lease_file(tmp_path).read_text() == before
    assert json.loads(before)["host"] == "other"


def test_release_and_the_updates_leave_a_lease_of_another_host_as_it_was(tmp_path: Path) -> None:
    held = foreign(tmp_path)
    before = lease_file(tmp_path).read_text()

    held.release(UNIT, "tab:a")
    held.mark_changes(UNIT, "tab:a", 3)
    held.record_session(UNIT, "tab:a", "s1")
    held.mark_committed(UNIT, "tab:a", "abc")
    held.release_checkout(UNIT, "app")

    assert lease_file(tmp_path).read_text() == before
