"""A fresh reading in Claude Code's own cache is used before the endpoint is asked.

The block `cachedUsageUtilization` in `~/.claude.json` decides a start, with no call, when its
`fetchedAtMs` is within `usage_claude_cache_minutes`, no window it describes has reset, and it is
fresher than the guard's own kept reading (spec: usage-pause). It is only a reading: nothing is
written to the guard's own cache.

Only the endpoint and the home directory are faked (`tests/usage_host.py`). A case that shows a
block is not used ends by showing the same file, made fresh, is: the difference is the block.
"""

import json
import logging
from datetime import UTC, datetime, timedelta

import pytest

from agent_build_kit.pipeline.usage_guard import Decision, decide_start, held_usage, refreshed_usage
from tests.usage_host import Host, called, configure, pause_at, payload, refusal

MINUTE = timedelta(minutes=1)
LABEL = "(claude.json, 6m old)"


@pytest.fixture(autouse=True)
def ninety_two(host: Host) -> None:
    configure(**pause_at(92))


def block_dict(age: timedelta, *, session: int = 20, resets_in: timedelta = timedelta(hours=2)):
    fetched = datetime.now(UTC) - age
    resets = (datetime.now(UTC) + resets_in).isoformat()
    return {
        "cachedUsageUtilization": {
            "fetchedAtMs": int(fetched.timestamp() * 1000),
            "utilization": {
                "five_hour": {"utilization": session, "resets_at": resets},
                "seven_day": {"utilization": 31, "resets_at": resets},
            },
        }
    }


def old_guard_reading(host: Host) -> None:
    """The guard's own reading, past the cache time and too close to the threshold to settle."""
    host.keep_reading(40 * MINUTE, payload(session=90.0, session_resets_in=timedelta(hours=3)))


def used(decision: Decision) -> bool:
    return decision.reason.endswith(LABEL)


def assert_a_fresh_block_is_used(host: Host) -> None:
    """The control: the block made fresh, over an old reading of the guard's own, decides."""
    old_guard_reading(host)
    host.keep_editor_reading(6 * MINUTE)
    asked = host.asked

    decision = decide_start()

    assert decision.may_start
    assert used(decision), decision.reason
    assert host.asked == asked


# --- 1.1 a fresh block decides -----------------------------------------------------------


def test_a_fresh_block_decides_a_start_without_a_call_and_touches_nothing_of_the_guards(
    host: Host,
) -> None:
    old_guard_reading(host)
    host.keep_editor_reading(6 * MINUTE)
    before = host.cache.read_bytes()

    decision = decide_start()

    assert decision.may_start
    assert used(decision), decision.reason
    assert host.asked == 0
    assert host.cache.read_bytes() == before


def test_the_status_command_s_readings_prefer_a_fresh_block_without_a_call(host: Host) -> None:
    old_guard_reading(host)
    host.keep_editor_reading(6 * MINUTE)

    refreshed = refreshed_usage()
    held = held_usage()

    for reading in (refreshed, held):
        assert reading is not None
        assert "claude.json" in reading.source
        assert reading.session_pct == 20
        assert abs(reading.age - 6 * MINUTE) < MINUTE
    assert host.asked == 0


# --- 1.2 how old a block may be ---------------------------------------------------------


@pytest.mark.parametrize(
    "age", [20 * MINUTE, timedelta(days=2)], ids=["twenty minutes", "two days"]
)
def test_a_block_older_than_the_window_is_not_used_whatever_the_file_s_own_time(
    host: Host, age: timedelta
) -> None:
    """The file is written just now in each case, so only `fetchedAtMs` can say it is old."""
    old_guard_reading(host)
    host.keep_editor_reading(age)
    host.answers = [payload(session=10.0)]

    decision = decide_start()

    assert host.asked == 1
    assert not used(decision)
    assert_a_fresh_block_is_used(host)


def test_a_window_of_zero_never_uses_the_block_and_the_order_is_todays(host: Host) -> None:
    configure(**pause_at(92), usage_claude_cache_minutes=0)
    old_guard_reading(host)
    host.keep_editor_reading(MINUTE)
    host.answers = [payload(session=10.0)]

    decision = decide_start()

    assert host.asked == 1
    assert "claude.json" not in decision.reason
    assert not [each for each in host.lines() if each["outcome"] == "claude-json"]

    configure(**pause_at(92))
    assert_a_fresh_block_is_used(host)


def test_a_window_above_the_stale_age_does_not_use_a_block_older_than_it(host: Host) -> None:
    configure(**pause_at(92), usage_claude_cache_minutes=90)
    old_guard_reading(host)
    host.keep_editor_reading(70 * MINUTE)
    host.answers = [payload(session=10.0)]

    decision = decide_start()

    assert host.asked == 1
    assert "claude.json" not in decision.reason

    host.keep_editor_reading(50 * MINUTE)
    asked = host.asked
    assert decide_start().reason.endswith("(claude.json, 50m old)")
    assert host.asked == asked


# --- 1.3 the fresher of the two ---------------------------------------------------------


def test_the_fresher_reading_wins_and_a_tie_goes_to_the_guard_s_own(host: Host) -> None:
    def decide(guard_age: timedelta, block_age: timedelta) -> Decision:
        host.keep_reading(guard_age, payload(session=30.0, session_resets_in=timedelta(hours=3)))
        host.keep_editor_reading(block_age, session=50)
        return decide_start()

    newer_block = decide(9 * MINUTE, 6 * MINUTE)
    assert used(newer_block), newer_block.reason

    older_block = decide(3 * MINUTE, 6 * MINUTE)
    assert "claude.json" not in older_block.reason
    assert "session 30%" in older_block.reason

    # The same instant on both, at the millisecond the block keeps.
    at = datetime.fromtimestamp(
        int((datetime.now(UTC) - 6 * MINUTE).timestamp() * 1000) / 1000, UTC
    )
    host.keep_reading(timedelta(0), payload(session=30.0, session_resets_in=timedelta(hours=3)))
    host.cache.write_text(
        json.dumps({**json.loads(host.cache.read_text()), "fetched_at": at.isoformat()})
    )
    host.keep_editor_reading(timedelta(0), session=50)
    block = json.loads((host.home / ".claude.json").read_text())
    block["cachedUsageUtilization"]["fetchedAtMs"] = int(at.timestamp() * 1000)
    (host.home / ".claude.json").write_text(json.dumps(block))
    tie = decide_start()
    assert "claude.json" not in tie.reason
    assert "session 30%" in tie.reason

    assert host.asked == 0


def test_a_fresh_block_is_used_when_the_guard_holds_no_fresh_reading_and_vice_versa(
    host: Host,
) -> None:
    host.keep_editor_reading(6 * MINUTE)
    only_block = decide_start()
    assert used(only_block), only_block.reason

    host.keep_reading(3 * MINUTE, payload(session=30.0, session_resets_in=timedelta(hours=3)))
    host.keep_editor_reading(40 * MINUTE, session=50)
    only_guard = decide_start()
    assert "session 30%" in only_guard.reason
    assert "claude.json" not in only_guard.reason

    assert host.asked == 0


# --- 1.4 what reads as absent -----------------------------------------------------------


def _without(key: str):
    def cut(block: dict) -> str:
        del block["cachedUsageUtilization"]["utilization"][key]
        return json.dumps(block)

    return cut


def _bad_time(block: dict) -> str:
    block["cachedUsageUtilization"]["fetchedAtMs"] = "soon"
    return json.dumps(block)


ABSENT = {
    "missing": None,
    "not json": lambda block: "{not json",
    "truncated": lambda block: json.dumps(block)[:-40],
    "no usage block": lambda block: json.dumps({"numStartups": 3}),
    "one window only": _without("seven_day"),
    "fetch time not a number": _bad_time,
}


def test_a_window_of_the_block_that_has_reset_means_it_is_not_used(host: Host) -> None:
    old_guard_reading(host)
    host.keep_editor_reading(6 * MINUTE, resets_in=-3 * MINUTE)
    host.answers = [payload(session=10.0)]

    decision = decide_start()

    assert host.asked == 1
    assert not used(decision)
    assert_a_fresh_block_is_used(host)


@pytest.mark.parametrize("case", list(ABSENT))
def test_an_unreadable_block_reads_as_absent_silently_and_never_as_zero(
    host: Host, case: str, caplog: pytest.LogCaptureFixture
) -> None:
    old_guard_reading(host)
    path = host.home / ".claude.json"
    cut = ABSENT[case]
    if cut is not None:
        path.write_text(cut(block_dict(6 * MINUTE)))
    host.answers = [payload(session=95.0)]

    with caplog.at_level(logging.DEBUG):
        decision = decide_start()

    assert host.asked == 1
    assert not decision.may_start, "a missing figure must not read as zero usage"
    assert not used(decision)
    assert not [r for r in caplog.records if "claude.json" in r.getMessage()]
    assert_a_fresh_block_is_used(host)


# --- 1.5 judged like any reading --------------------------------------------------------


def test_a_fresh_block_over_a_threshold_refuses_and_pauses_until_the_relief_without_a_call(
    host: Host,
) -> None:
    old_guard_reading(host)
    host.keep_editor_reading(6 * MINUTE, session=95, resets_in=timedelta(hours=2))

    decision = decide_start()

    assert not decision.may_start
    assert "claude.json" in decision.reason
    assert host.asked == 0
    assert decision.resume_at is not None
    assert abs(decision.resume_at - (datetime.now(UTC) + timedelta(hours=2))) < 2 * MINUTE


def test_a_fresh_block_inside_the_minimum_interval_allows_without_the_wait(host: Host) -> None:
    old_guard_reading(host)
    called(host, 2 * MINUTE)
    host.keep_editor_reading(6 * MINUTE)

    decision = decide_start()

    assert decision.may_start
    assert "interval" not in decision.reason.lower()
    assert used(decision), decision.reason
    assert host.asked == 0


def test_the_credits_rule_does_not_fire_on_a_block_reading(host: Host) -> None:
    """The guard's own older reading has credits on and a window full; the block, fresher,
    is decided by the thresholds alone."""
    host.keep_reading(40 * MINUTE, payload(session=100.0, session_resets_in=timedelta(hours=3)))
    host.keep_editor_reading(6 * MINUTE)

    decision = decide_start()

    assert decision.may_start
    assert "credit" not in decision.reason.lower()
    assert used(decision), decision.reason
    assert host.asked == 0


# --- 1.8 only a reading ----------------------------------------------------------------


def test_a_stale_block_with_no_kept_reading_is_no_base_and_the_stale_rule_applies(
    host: Host,
) -> None:
    host.keep_editor_reading(2 * timedelta(hours=1))
    host.answers = [refusal()]

    decision = decide_start()

    assert not decision.may_start
    assert "stale" in decision.reason
    assert "estimate" not in decision.reason
    assert host.asked == 1

    # The refusal left a cool-down, which may be named after the source; the block is still used.
    host.keep_editor_reading(6 * MINUTE)
    assert "claude.json, 6m old" in decide_start().reason
    assert host.asked == 1


def test_a_decision_from_a_block_leaves_the_guard_s_cache_and_its_cool_down_alone(
    host: Host,
) -> None:
    old_guard_reading(host)
    kept = json.loads(host.cache.read_text())
    until = datetime.now(UTC) + 10 * MINUTE
    host.cache.write_text(json.dumps({**kept, "cooldown_until": until.isoformat()}))
    before = host.cache.read_bytes()
    host.keep_editor_reading(6 * MINUTE)

    decision = decide_start()

    assert used(decision), decision.reason
    assert host.cache.read_bytes() == before
    assert not [each for each in host.lines() if each["outcome"] == "rate_limited"]
    assert host.asked == 0
