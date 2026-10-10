"""Pausing when the usage window runs low, and coming back.

The guard decides *whether* to start a unit; this is what happens after it
says no (docs/architecture.md). The way back is the tick, which the timer runs
every few minutes and which asks the guard again — so a pause records when and
why, and needs no resume of its own.

- **A pause is visible.** A marker file and a run-log line, so the state is
  "paused until 20:51" rather than "mysteriously idle since lunchtime".
- **The guard's latest answer wins**, sooner or later; only a refusal from the
  model itself is never shortened.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit.pipeline.pause import (
    RESUME_GRACE,
    Pause,
    clear_pause,
    is_paused,
    pause_until,
)


def test_pausing_records_when_and_why(tmp_path: Path) -> None:
    """The deadline carries the grace period: the pause is in force until
    just *after* the window resets, not up to the boundary itself."""
    resets_at = datetime.now(UTC) + timedelta(hours=2)

    pause_until(
        resets_at,
        reason="session usage at 88%",
        marker=tmp_path / "paused.json",
    )

    state = is_paused(tmp_path / "paused.json")
    assert isinstance(state, Pause)
    assert "88%" in state.reason
    assert state.until == resets_at + RESUME_GRACE


def test_an_unknown_reset_time_still_sets_a_deadline(tmp_path: Path) -> None:
    """The usage endpoint can fail; the marker still says when to expect more."""
    state = pause_until(None, reason="usage is unknown", marker=tmp_path / "paused.json")

    assert state.until > datetime.now(UTC)


def test_nothing_is_paused_by_default(tmp_path: Path) -> None:
    assert is_paused(tmp_path / "paused.json") is None


def test_a_pause_expires_on_its_own(tmp_path: Path) -> None:
    """A deadline that has passed is not a pause, whatever the marker says."""
    (tmp_path / "paused.json").write_text(
        json.dumps(
            {
                "until": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
                "reason": "already over",
            }
        )
    )

    assert is_paused(tmp_path / "paused.json") is None


def test_clearing_a_pause_removes_it(tmp_path: Path) -> None:
    pause_until(
        datetime.now(UTC) + timedelta(hours=1),
        reason="x",
        marker=tmp_path / "paused.json",
    )

    clear_pause(tmp_path / "paused.json")

    assert is_paused(tmp_path / "paused.json") is None


def test_a_corrupt_marker_does_not_wedge_the_pipeline(tmp_path: Path) -> None:
    """Unlike the unit store, being unable to read this should not stop work:
    the usage guard is checked again on the next tick anyway."""
    marker = tmp_path / "paused.json"
    marker.write_text("{not json")

    assert is_paused(marker) is None


def test_the_guards_latest_answer_replaces_an_earlier_one(tmp_path: Path) -> None:
    """Worked out from a newer reading — a threshold raised by hand, the ramp
    offering room — a sooner deadline is the right one, not a risk."""
    marker = tmp_path / "paused.json"
    pause_until(datetime.now(UTC) + timedelta(hours=3), reason="weekly", marker=marker)
    sooner = datetime.now(UTC) + timedelta(minutes=20)

    pause_until(sooner, reason="session", marker=marker)

    state = is_paused(marker)
    assert state is not None
    assert state.until == sooner + RESUME_GRACE
    assert state.kind == "usage"


def test_a_rate_limit_pause_is_never_shortened(tmp_path: Path) -> None:
    """The model refused; the usage endpoint can still show room, so its
    reading must not end that pause early."""
    marker = tmp_path / "paused.json"
    later = datetime.now(UTC) + timedelta(hours=2)
    pause_until(later, reason="rate limited", marker=marker, kind="rate_limit")

    pause_until(datetime.now(UTC) + timedelta(minutes=5), reason="session", marker=marker)

    state = is_paused(marker)
    assert state is not None
    assert state.kind == "rate_limit"
    assert state.until == later + RESUME_GRACE


def test_a_pause_being_rewritten_is_never_read_as_over(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A tick reads the marker while a build records a pause, so a reader
    looking half way through a write must see a whole pause, not a torn file
    it would take for "not paused"."""
    marker = tmp_path / "paused.json"
    pause_until(
        datetime.now(UTC) + timedelta(hours=1), reason="the guard", marker=marker, kind="rate_limit"
    )
    seen: list[Pause | None] = []
    real_write_text = Path.write_text

    def interrupted(self: Path, data: str, *args: object, **kwargs: object) -> int:
        """Writes the first half, lets a reader look, then writes the rest."""
        real_write_text(self, data[: len(data) // 2])
        seen.append(is_paused(marker))
        return real_write_text(self, data, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "write_text", interrupted)

    pause_until(
        datetime.now(UTC) + timedelta(hours=3), reason="the model", marker=marker, kind="rate_limit"
    )

    assert seen
    assert all(state is not None and state.kind == "rate_limit" for state in seen)


def test_a_failed_write_leaves_the_marker_and_nothing_beside_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = tmp_path / "paused.json"
    pause_until(datetime.now(UTC) + timedelta(hours=1), reason="the guard", marker=marker)

    def full_disk(self: Path, data: str, *args: object, **kwargs: object) -> int:
        raise OSError("no space left on device")

    monkeypatch.setattr(Path, "write_text", full_disk)

    with pytest.raises(OSError):
        pause_until(datetime.now(UTC) + timedelta(hours=3), reason="the model", marker=marker)

    monkeypatch.undo()
    state = is_paused(marker)
    assert state is not None
    assert state.reason == "the guard"
    assert {path.name for path in tmp_path.iterdir()} == {"paused.json", "paused.json.lock"}


def test_clearing_leaves_a_rate_limit_pause_in_force(tmp_path: Path) -> None:
    """A round clears a pause once the guard finds room; a build may have
    recorded the model's refusal since that round last looked."""
    marker = tmp_path / "paused.json"
    pause_until(
        datetime.now(UTC) + timedelta(hours=1), reason="the model", marker=marker, kind="rate_limit"
    )

    left = clear_pause(marker)

    state = is_paused(marker)
    assert state is not None
    assert state.kind == "rate_limit"
    assert left == state


def test_clearing_ends_a_usage_pause(tmp_path: Path) -> None:
    marker = tmp_path / "paused.json"
    pause_until(datetime.now(UTC) + timedelta(hours=1), reason="the guard", marker=marker)

    assert clear_pause(marker) is None

    assert is_paused(marker) is None
