"""The ~/.claude.json fallback source, and the pause rules.

The live endpoint (tests/test_usage_live.py) is the primary source. This file
covers what happens when it can't answer.

Unattended work must not eat the usage window the user needs for their own
sessions, and this account has credits enabled past the plan limit, so running
to 100% spends real money rather than stopping (docs/architecture.md).

That cache is written when an *interactive* session talks to the API; a
headless `claude -p` run does not refresh it — verified — so it goes stale
exactly when the runner is working alone. Everything below is about being
honest when that happens: an unknown reading pauses, it doesn't assume
headroom.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit.pipeline.usage_guard import (
    may_start_unit,
    read_cached_usage,
)


def write_anchor(
    tmp_path: Path,
    *,
    session_pct: int = 10,
    weekly_pct: int = 10,
    fetched: datetime | None = None,
    resets_in: timedelta = timedelta(hours=2),
    # Far enough out that the weekly ramp is not in play unless a test asks
    # for it: the two windows reset on their own schedules, days apart.
    weekly_resets_in: timedelta = timedelta(days=3),
) -> Path:
    fetched = fetched or datetime.now(UTC)
    resets_at = (datetime.now(UTC) + resets_in).isoformat()
    weekly_resets_at = (datetime.now(UTC) + weekly_resets_in).isoformat()
    path = tmp_path / ".claude.json"
    path.write_text(
        json.dumps(
            {
                "cachedUsageUtilization": {
                    "fetchedAtMs": int(fetched.timestamp() * 1000),
                    "utilization": {
                        "five_hour": {"utilization": session_pct, "resets_at": resets_at},
                        "seven_day": {"utilization": weekly_pct, "resets_at": weekly_resets_at},
                    },
                }
            }
        )
    )
    return path


def test_reads_both_windows_and_when_it_was_written(tmp_path: Path) -> None:
    path = write_anchor(tmp_path, session_pct=32, weekly_pct=4)

    anchor = read_cached_usage(path)

    assert anchor is not None
    assert anchor.session_pct == 32
    assert anchor.weekly_pct == 4
    assert anchor.resets_at is not None and anchor.resets_at > datetime.now(UTC)
    # Each window resets on its own clock, and the ramp needs both.
    assert anchor.weekly_resets_at is not None
    assert anchor.weekly_resets_at > anchor.resets_at


def test_a_missing_file_is_not_an_error_but_is_unknown(tmp_path: Path) -> None:
    """Claude Code may simply never have written it on this machine."""
    assert read_cached_usage(tmp_path / "nope.json") is None


@pytest.mark.parametrize(
    "content",
    [
        "{}",
        '{"cachedUsageUtilization": {}}',
        '{"cachedUsageUtilization": {"utilization": {"five_hour": {}}}}',
        "not json at all",
    ],
)
def test_an_unrecognized_shape_reads_as_unknown(content: str, tmp_path: Path) -> None:
    """The field is undocumented internal state and may change shape in any
    Claude Code release. A parse failure must never look like 0% used."""
    path = tmp_path / ".claude.json"
    path.write_text(content)

    assert read_cached_usage(path) is None


def test_starts_a_unit_when_well_under_the_threshold(tmp_path: Path) -> None:
    decision = may_start_unit(read_cached_usage(write_anchor(tmp_path, session_pct=10)))

    assert decision.may_start
    assert decision.resume_at is None


def test_pauses_at_the_threshold_not_just_above_it(tmp_path: Path) -> None:
    """70 means 70: 'at or above' is the rule, so the boundary case pauses."""
    decision = may_start_unit(read_cached_usage(write_anchor(tmp_path, session_pct=70)))

    assert not decision.may_start


def test_either_window_can_trigger_the_pause(tmp_path: Path) -> None:
    """The weekly window is the one that ends a working day if it runs out,
    so it gates starting work just as the session window does."""
    decision = may_start_unit(
        read_cached_usage(write_anchor(tmp_path, session_pct=5, weekly_pct=85))
    )

    assert not decision.may_start
    assert "weekly" in decision.reason


def test_pausing_says_when_to_resume(tmp_path: Path) -> None:
    anchor = read_cached_usage(write_anchor(tmp_path, session_pct=90, resets_in=timedelta(hours=3)))

    decision = may_start_unit(anchor)

    assert decision.resume_at is not None
    assert decision.resume_after_seconds > 0
    # The reset itself: the grace that keeps a resume from racing the window
    # boundary is added once, when the pause is written (`pause_until`).
    assert decision.resume_after_seconds == pytest.approx(timedelta(hours=3).total_seconds(), abs=5)


def test_an_unknown_anchor_pauses(tmp_path: Path) -> None:
    """Fail safe. Assuming headroom we can't see is how the account ends up
    spending credits unattended."""
    decision = may_start_unit(None)

    assert not decision.may_start
    assert "unknown" in decision.reason.lower()


def test_an_unknown_anchor_still_schedules_a_retry(tmp_path: Path) -> None:
    """A pause with no resume would stop the pipeline until someone noticed."""
    decision = may_start_unit(None)

    assert decision.resume_after_seconds > 0


def test_a_stale_anchor_is_treated_as_unknown(tmp_path: Path) -> None:
    """A headless run never refreshes the cache, so an old reading says
    nothing about what the unattended work since then has consumed."""
    old = datetime.now(UTC) - timedelta(hours=6)
    anchor = read_cached_usage(write_anchor(tmp_path, session_pct=10, fetched=old))

    decision = may_start_unit(anchor)

    assert not decision.may_start
    assert "stale" in decision.reason.lower()
