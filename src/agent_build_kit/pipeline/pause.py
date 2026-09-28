"""Pausing when the usage window runs low, and scheduling the return.

`usage_guard` decides whether a unit may start. This is what happens when it
says no (docs/architecture.md).

A pause that merely stops would leave the pipeline dead until somebody
noticed, so it always schedules its own return — including when the reason for
pausing is that the usage couldn't be read at all, which is exactly the case
where waiting for a human is least likely to work.

It is also deliberately visible. A marker file plus a run-log line means the
state reads as "paused until 20:51 because the weekly window is at 92%",
rather than "idle since lunchtime for reasons unknown".
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path

from agent_build_kit.config import active_root
from agent_build_kit.model import Frozen

# Just after the reset, never exactly on it: a resume racing the window
# boundary finds it still full and pauses again.
RESUME_GRACE = timedelta(minutes=2)

# When the reset time is unknown, try again on this cadence rather than
# waiting for a human.
UNKNOWN_RETRY = timedelta(minutes=30)

# The tick, through the console script the framework installs. It once named
# a task that did not exist, so every scheduled resume failed on launch —
# silently, since a failed transient unit tells nobody. A test checks this
# names a real entry point.
RESUME_COMMAND = "uv run abk tick"

# Same PATH the timer's service unit sets, for the same reason: a user systemd
# unit does not source a shell profile, and uv, claude, gh and git-branchless
# live in ~/.local/bin; node (for the OpenSpec CLI through npx) may be Volta's.
RESUME_PATH = (
    f"{Path.home()}/.local/bin:{Path.home()}/.volta/bin:"
    "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
)

Scheduler = Callable[[float, str], None]


class Pause(Frozen):
    until: datetime
    reason: str


def systemd_resume(
    seconds: float,
    command: str,
    *,
    working_directory: Path | None = None,
    run: Callable | None = None,
) -> None:
    """Schedule a one-shot resume, matching how the timers run the tick.

    In the planning repo, with uv on the PATH. A transient unit otherwise
    starts in the user manager's environment — neither — and fails before
    running anything.
    """
    run = run or subprocess.run
    working_directory = working_directory or active_root() or Path.cwd()
    run(
        [
            "systemd-run",
            "--user",
            f"--on-active={int(seconds)}s",
            f"--working-directory={working_directory}",
            f"--setenv=PATH={RESUME_PATH}",
            "--unit",
            f"spec-driven-resume-{int(datetime.now(UTC).timestamp())}",
            "/bin/sh",
            "-c",
            command,
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def is_paused(marker: Path) -> Pause | None:
    """The current pause, if one is still in force.

    A pause whose deadline has passed is treated as over even if the scheduled
    resume never fired — a reboot or a disabled timer shouldn't strand the
    pipeline. An unreadable marker is treated as "not paused": unlike the unit
    store, guessing wrong here costs one usage check, not rebuilt work.
    """
    try:
        data = json.loads(marker.read_text())
        until = datetime.fromisoformat(data["until"])
    except (OSError, ValueError, KeyError, TypeError):
        return None

    if until <= datetime.now(UTC):
        return None
    return Pause(until=until, reason=str(data.get("reason", "")))


def pause_until(
    until: datetime | None,
    *,
    reason: str,
    marker: Path,
    schedule: Scheduler | None = None,
    command: str = RESUME_COMMAND,
) -> Pause:
    """Record a pause and schedule the resume that ends it."""
    schedule = schedule or partial(systemd_resume, working_directory=active_root())

    deadline = (until + RESUME_GRACE) if until else (datetime.now(UTC) + UNKNOWN_RETRY)

    existing = is_paused(marker)
    if existing and existing.until > deadline:
        # Don't shorten an existing pause: the earlier deadline would start
        # work into a window that is still full.
        return existing

    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        json.dumps(
            {"until": deadline.isoformat(), "reason": reason, "at": datetime.now(UTC).isoformat()},
            indent=2,
        )
        + "\n"
    )

    schedule(max(1.0, (deadline - datetime.now(UTC)).total_seconds()), command)
    return Pause(until=deadline, reason=reason)


def clear_pause(marker: Path) -> None:
    marker.unlink(missing_ok=True)
