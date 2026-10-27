"""The e2e-test lock's record names its host; a foreign one cannot be checked from here."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_build_kit.pipeline import host
from agent_build_kit.pipeline.e2e import LockRecord, hold_lock, lock_status_line, read_lock_record
from tests.e2e_lock_fakes import Foreign, SleepingTime, dead_pid, held, install_clock, record_line


@pytest.fixture(autouse=True)
def on_box(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(host, "this_host", lambda: "box")


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> SleepingTime:
    return install_clock(monkeypatch)


def name_host(other: Foreign, record_host: str) -> None:
    """The record `other` left, rewritten to name `record_host`."""
    record = json.loads(record_line("other/1", dead_pid()))
    other.handle.seek(0)
    other.handle.truncate()
    other.handle.write(json.dumps({**record, "host": record_host}) + "\n")
    other.handle.flush()


def test_the_record_written_carries_the_host_and_an_old_one_has_none(tmp_path: Path) -> None:
    path = tmp_path / "e2e.lock"
    with hold_lock(path, holder="feature/1"):
        record = read_lock_record(path.read_text())
        assert record is not None
        assert record.host == "box"

    assert LockRecord.model_validate_json(record_line("a/1", 5)).host == ""


def test_a_record_of_another_host_is_named_in_the_status_and_not_called_gone(
    tmp_path: Path,
) -> None:
    path = tmp_path / "e2e.lock"
    with held(path) as other:
        name_host(other, "other")
        line = lock_status_line(path)
        assert line is not None
        assert "other" in line
        assert "cannot be checked from here" in line
        assert "is gone" not in line

        name_host(other, "box")
        line = lock_status_line(path)
        assert line is not None
        assert "is gone" in line


def test_the_waiting_message_names_a_foreign_host(tmp_path: Path, clock: SleepingTime) -> None:
    path = tmp_path / "e2e.lock"
    said: list[str] = []
    with held(path) as other:
        name_host(other, "other")
        with pytest.raises(TimeoutError), hold_lock(path, 1.0, on_wait=said.append):
            pass

    assert said
    assert "other" in said[0]
    assert "cannot be checked from here" in said[0]
    assert "is gone" not in said[0]


def test_a_free_lock_with_a_record_of_another_host_does_not_claim_its_process_is_gone(
    tmp_path: Path,
) -> None:
    path = tmp_path / "e2e.lock"
    record = json.loads(record_line("other/1", dead_pid()))
    path.write_text(json.dumps({**record, "host": "other"}) + "\n")

    line = lock_status_line(path)

    assert line is not None
    assert "other" in line
    assert "is gone" not in line
