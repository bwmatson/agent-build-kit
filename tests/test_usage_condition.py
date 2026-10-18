"""A scratch tick that built nothing and left a usage or rate-limit pause ends its test as a
skip that names the pause; anything else is left to fail as it did."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit.pipeline.pause import PAUSE_MARKER
from tests.scratch_fakes import HandScratch, hand_scratch
from tests.usage_condition import skip_on_usage_condition

BRANCH = "spec/feature/1"
USAGE_REASON = "session usage at 91% (threshold 70%, live)"
LIMIT_REASON = "You've hit your limit · resets 5pm"


def mark(scratch: HandScratch, kind: str, reason: str, *, hours: float = 1) -> None:
    until = datetime.now(UTC) + timedelta(hours=hours)
    (scratch.state / PAUSE_MARKER).write_text(
        json.dumps({"until": until.isoformat(), "reason": reason, "kind": kind})
    )


def skip_reason(scratch: HandScratch) -> str:
    with pytest.raises(pytest.skip.Exception) as raised:
        skip_on_usage_condition(scratch, BRANCH)
    return str(raised.value)


def test_a_usage_pause_skips_with_the_reading_the_threshold_and_why(tmp_path: Path) -> None:
    scratch = hand_scratch(tmp_path)
    mark(scratch, "usage", USAGE_REASON)

    reason = skip_reason(scratch)

    for part in ("91%", "70%", "usage is an environment condition", "the build was not attempted"):
        assert part in reason, reason


def test_a_rate_limit_pause_skips_with_the_markers_reason(tmp_path: Path) -> None:
    scratch = hand_scratch(tmp_path)
    mark(scratch, "rate_limit", LIMIT_REASON)

    assert LIMIT_REASON in skip_reason(scratch)


def test_a_network_pause_does_not_skip(tmp_path: Path) -> None:
    scratch = hand_scratch(tmp_path)
    mark(scratch, "network", "network unreachable")

    skip_on_usage_condition(scratch, BRANCH)


def test_no_marker_does_not_skip(tmp_path: Path) -> None:
    skip_on_usage_condition(hand_scratch(tmp_path), BRANCH)


def test_an_expired_marker_does_not_skip(tmp_path: Path) -> None:
    scratch = hand_scratch(tmp_path)
    mark(scratch, "usage", USAGE_REASON, hours=-1)

    skip_on_usage_condition(scratch, BRANCH)


def test_a_marker_next_to_a_built_unit_does_not_skip(tmp_path: Path) -> None:
    scratch = hand_scratch(tmp_path, branch=BRANCH)
    mark(scratch, "usage", USAGE_REASON)

    skip_on_usage_condition(scratch, BRANCH)
