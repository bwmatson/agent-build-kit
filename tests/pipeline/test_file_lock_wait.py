"""`file_lock` waits a bounded time for a held lock.

The holder is a second open of the same file, which contends as another process does; the
clock the wait reads moves only as the waiter sleeps."""

from __future__ import annotations

import fcntl
from pathlib import Path

import pytest

from agent_build_kit.pipeline import file_lock as file_lock_module
from agent_build_kit.pipeline.file_lock import LockTimeout, file_lock, try_file_lock
from agent_build_kit.settings import settings
from tests.e2e_lock_fakes import SleepingTime, install_clock


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> SleepingTime:
    return install_clock(monkeypatch, module=file_lock_module)


def test_a_held_lock_times_out_naming_the_path_and_the_setting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: SleepingTime
) -> None:
    path = tmp_path / "units.json.lock"
    monkeypatch.setattr(settings, "lock_wait_seconds", 1.0)
    with path.open("a") as holder:
        fcntl.flock(holder, fcntl.LOCK_EX)

        with pytest.raises(LockTimeout) as raised, file_lock(path):
            pass

        message = str(raised.value)
        assert str(path) in message
        assert "for 1s" in message
        assert "ABK_LOCK_WAIT_SECONDS" in message
        assert clock.elapsed() >= 1.0
        # The holder still holds it.
        with path.open("a") as probe:
            with pytest.raises(BlockingIOError):
                fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_the_message_shows_the_seconds_of_the_setting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: SleepingTime
) -> None:
    path = tmp_path / "a.lock"
    monkeypatch.setattr(settings, "lock_wait_seconds", 1.5)
    with path.open("a") as holder:
        fcntl.flock(holder, fcntl.LOCK_EX)

        with pytest.raises(LockTimeout) as raised, file_lock(path):
            pass

    assert "for 1.5s" in str(raised.value)


def test_a_lock_released_during_the_wait_is_taken(tmp_path: Path, clock: SleepingTime) -> None:
    path = tmp_path / "a.lock"
    holder = path.open("a")
    fcntl.flock(holder, fcntl.LOCK_EX)

    def let_go() -> None:
        fcntl.flock(holder, fcntl.LOCK_UN)
        holder.close()

    clock.release_at(0.2, let_go)
    with file_lock(path, timeout=100.0):
        taken = True

    assert taken
    assert clock.elapsed() >= 0.2


def test_the_timeout_argument_overrides_the_setting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: SleepingTime
) -> None:
    path = tmp_path / "a.lock"
    monkeypatch.setattr(settings, "lock_wait_seconds", 3600.0)
    with path.open("a") as holder:
        fcntl.flock(holder, fcntl.LOCK_EX)

        with pytest.raises(LockTimeout), file_lock(path, timeout=0.2):
            pass

    assert clock.elapsed() < 3600.0


def test_the_try_form_yields_false_at_once_and_a_timeout_is_a_timeout_error(
    tmp_path: Path, clock: SleepingTime
) -> None:
    path = tmp_path / "a.lock"
    with path.open("a") as holder:
        fcntl.flock(holder, fcntl.LOCK_EX)

        with try_file_lock(path) as taken:
            assert taken is False

        assert clock.elapsed() == 0
        assert issubclass(LockTimeout, TimeoutError)
        with pytest.raises(LockTimeout), file_lock(path, timeout=0.1):
            pass
