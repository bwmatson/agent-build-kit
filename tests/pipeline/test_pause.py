"""Pausing when the usage window runs low, and coming back.

The guard decides *whether* to start a unit; this is what happens after it
says no (docs/architecture.md). A pause that just stops would
leave the pipeline dead until someone noticed, so it schedules its own return.

Two things have to hold for that to be safe:

- **A resume is always scheduled**, even when the reason for pausing is that
  we couldn't read the usage at all.
- **A pause is visible.** A marker file and a run-log line, so the state is
  "paused until 20:51" rather than "mysteriously idle since lunchtime".
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent_build_kit.pipeline.pause import (
    RESUME_COMMAND,
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
        schedule=lambda s, c: None,
    )

    state = is_paused(tmp_path / "paused.json")
    assert isinstance(state, Pause)
    assert "88%" in state.reason
    assert state.until == resets_at + RESUME_GRACE


def test_a_resume_is_scheduled_for_just_after_the_reset(tmp_path: Path) -> None:
    """Resuming exactly at the boundary would find the window still full and
    pause again immediately."""
    scheduled: list[tuple[float, str]] = []
    until = datetime.now(UTC) + timedelta(hours=1)

    pause_until(
        until,
        reason="weekly usage at 92%",
        marker=tmp_path / "paused.json",
        schedule=lambda seconds, command: scheduled.append((seconds, command)),
    )

    seconds, command = scheduled[0]
    assert seconds > timedelta(hours=1).total_seconds()
    assert command == RESUME_COMMAND


def test_an_unknown_reset_time_still_schedules_a_retry(tmp_path: Path) -> None:
    """The usage endpoint can fail; a pause with no return would stop the
    pipeline until a human noticed."""
    scheduled: list[tuple[float, str]] = []

    pause_until(
        None,
        reason="usage is unknown",
        marker=tmp_path / "paused.json",
        schedule=lambda seconds, command: scheduled.append((seconds, command)),
    )

    assert scheduled
    assert scheduled[0][0] > 0


def test_nothing_is_paused_by_default(tmp_path: Path) -> None:
    assert is_paused(tmp_path / "paused.json") is None


def test_a_pause_expires_on_its_own(tmp_path: Path) -> None:
    """If the scheduled resume never fires — a reboot, a disabled timer — the
    next tick should still pick the work up rather than wait forever."""
    pause_until(
        datetime.now(UTC) - timedelta(hours=1),
        reason="already over",
        marker=tmp_path / "paused.json",
        schedule=lambda s, c: None,
    )

    assert is_paused(tmp_path / "paused.json") is None


def test_clearing_a_pause_removes_it(tmp_path: Path) -> None:
    pause_until(
        datetime.now(UTC) + timedelta(hours=1),
        reason="x",
        marker=tmp_path / "paused.json",
        schedule=lambda s, c: None,
    )

    clear_pause(tmp_path / "paused.json")

    assert is_paused(tmp_path / "paused.json") is None


def test_a_corrupt_marker_does_not_wedge_the_pipeline(tmp_path: Path) -> None:
    """Unlike the unit store, being unable to read this should not stop work:
    the usage guard is checked again on the next tick anyway."""
    marker = tmp_path / "paused.json"
    marker.write_text("{not json")

    assert is_paused(marker) is None


def test_pausing_twice_keeps_the_later_deadline(tmp_path: Path) -> None:
    """A second pause while paused shouldn't shorten the wait and start work
    into a window that is still full."""
    marker = tmp_path / "paused.json"
    later = datetime.now(UTC) + timedelta(hours=3)
    pause_until(later, reason="weekly", marker=marker, schedule=lambda s, c: None)

    pause_until(
        datetime.now(UTC) + timedelta(minutes=5),
        reason="session",
        marker=marker,
        schedule=lambda s, c: None,
    )

    state = is_paused(marker)
    assert state is not None
    assert state.until == later + RESUME_GRACE


def test_the_resume_command_names_a_task_that_exists() -> None:
    """It named `poe spec-driven poll`, a task that never existed, so every
    scheduled resume failed on launch and the pause's other half was dead code.
    Nothing noticed, because a failed transient unit is silent."""
    import tomllib
    from pathlib import Path

    from agent_build_kit.pipeline import pause

    scripts = tomllib.loads((Path(__file__).resolve().parents[2] / "pyproject.toml").read_text())[
        "project"
    ]["scripts"]
    words = pause.RESUME_COMMAND.split()
    assert words[:2] == ["uv", "run"]
    assert words[2] in scripts, "the resume must name a console script the framework installs"
    assert words[3] == "tick"


def test_a_resume_runs_in_the_repo_with_uv_on_its_path() -> None:
    """A transient unit starts in the user manager's environment: not this
    repo's directory, and not a PATH that includes ~/.local/bin where uv lives.
    The service unit for the timer sets both for the same reason."""
    from agent_build_kit.pipeline import pause

    seen: list[list[str]] = []
    pause.systemd_resume(
        60,
        pause.RESUME_COMMAND,
        working_directory=Path("/planning"),
        run=lambda args, **k: seen.append(args),
    )

    args = " ".join(seen[0])
    assert "--working-directory=/planning" in args
    assert ".local/bin" in args
