"""A lock held under the old file name is honoured until it is released, and removed once taken."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.compat_names import old_spelling
from agent_build_kit.model import TestTier
from agent_build_kit.pipeline.e2e import stack_lock
from tests.tier2_lock_fakes import Foreign, SleepingTime, install_clock

OLD_LOCK = f"{old_spelling(TestTier.E2E_TEST)}.lock"


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> SleepingTime:
    return install_clock(monkeypatch)


def test_a_holder_of_the_old_file_keeps_the_new_lock_busy(
    tmp_path: Path, clock: SleepingTime
) -> None:
    other = Foreign(tmp_path / OLD_LOCK)

    with pytest.raises(TimeoutError):
        with stack_lock(tmp_path / "e2e.lock", timeout=2):
            pass

    other.release()


def test_the_lock_is_taken_once_the_old_holder_lets_go_and_the_old_file_stays(
    tmp_path: Path, clock: SleepingTime
) -> None:
    other = Foreign(tmp_path / OLD_LOCK)
    clock.release_at(30, other.release)
    taken = False

    with stack_lock(tmp_path / "e2e.lock", timeout=120):
        taken = True

    assert taken
    assert clock.elapsed() >= 30
    assert (tmp_path / OLD_LOCK).exists()


def test_an_old_holder_still_blocks_a_later_lock_after_an_earlier_one_was_taken_and_released(
    tmp_path: Path, clock: SleepingTime
) -> None:
    (tmp_path / OLD_LOCK).touch()
    with stack_lock(tmp_path / "e2e.lock", timeout=2):
        pass
    other = Foreign(tmp_path / OLD_LOCK)

    with pytest.raises(TimeoutError):
        with stack_lock(tmp_path / "e2e.lock", timeout=2):
            pass

    other.release()


def test_without_an_old_file_none_is_created(tmp_path: Path, clock: SleepingTime) -> None:
    with stack_lock(tmp_path / "e2e.lock", timeout=2):
        pass

    assert not (tmp_path / OLD_LOCK).exists()
