"""A refused or unreadable usage read allows a start while the reading kept leaves ample headroom.

When the endpoint cannot be asked, each window is estimated as the reading kept in the
guard's cache plus a flat allowance for every unit that has spent since, and a start is
allowed while, in both windows, the estimate plus a margin is under the threshold
(spec: usage-pause). A window that has reset since is estimated from its reset, and the
number of starts made on one reading is capped.

Only the endpoint and the home directory are faked (`tests/usage_host.py`); the ledger is
the real file beside the cache.
"""

import json
import re
from datetime import UTC, datetime, timedelta

import pytest

from agent_build_kit.pipeline.usage_guard import decide_start, next_call_at
from agent_build_kit.pipeline.usage_ledger import LEDGER_NAME, UsageRecord, append_record
from tests.usage_host import Host, configure, pause_at, payload, refusal

MINUTE = timedelta(minutes=1)
HOUR = 60 * MINUTE


@pytest.fixture(autouse=True)
def ninety_two(host: Host) -> None:
    """The session pauses at 92 and the weekly at 80, neither ramping."""
    thresholds()


def thresholds(**limits: object) -> None:
    configure(session={"usage_pause_pct": 92}, weekly={"usage_pause_pct": 80}, **limits)


def keep(host: Host, age: timedelta, **body: object) -> None:
    host.keep_reading(age, payload(**body))  # type: ignore[arg-type]


def refusal_record(ago: timedelta) -> dict:
    return {
        "at": (datetime.now(UTC) - ago).isoformat(),
        "caller": "guard",
        "outcome": "rate_limited",
        "status": 429,
        "latency_ms": 100,
        "headers": {"retry-after": "0"},
    }


def refused_ago(host: Host, ago: timedelta = 2 * MINUTE) -> None:
    """The endpoint answered 429 with a retry time of zero `ago` ago; a cool-down is in force."""
    host.seed(refusal_record(ago))
    kept = json.loads(host.cache.read_text())
    until = datetime.now(UTC) + 3 * MINUTE
    host.cache.write_text(json.dumps({**kept, "cooldown_until": until.isoformat()}))


def observed(host: Host, **body: object) -> None:
    """The reading and the refusal the pipeline was found paused on."""
    keep(host, 89 * MINUTE, **{"session": 0.0, "weekly": 65.0, **body})  # type: ignore[arg-type]
    refused_ago(host)


def spent(host: Host, unit: str, *ago: timedelta) -> None:
    """The ledger holds a record of `unit` for each time in `ago`."""
    path = host.cache.parent / LEDGER_NAME
    for each in ago:
        at = datetime.now(UTC) - each
        append_record(path, UsageRecord(at=at.isoformat(), unit=unit, node="implement"))


def admitted(host: Host) -> list[str]:
    return json.loads(host.cache.read_text()).get("estimate_units", [])


def admit(host: Host, *units: str) -> None:
    """The cache file records `units` as admitted on an estimate since the reading."""
    kept = json.loads(host.cache.read_text())
    host.cache.write_text(json.dumps({**kept, "estimate_units": list(units)}))


# --- 1.1 the observed case ---------------------------------------------------------------


def test_a_refused_read_with_headroom_allows_a_start_on_an_estimate_without_a_call(
    host: Host,
) -> None:
    observed(host)

    decision = decide_start()

    assert decision.may_start
    assert host.asked == 0
    assert "89m old" in decision.reason
    assert "session ~0% estimated (0% read + 0% spent)" in decision.reason
    assert "weekly ~65% estimated (65% read + 0% spent)" in decision.reason
    assert "allowing starts" in decision.reason


def test_a_read_that_fails_after_a_call_is_decided_on_the_estimate_too(host: Host) -> None:
    keep(host, 89 * MINUTE, session=0.0, weekly=65.0)
    host.answers = [refusal(retry_after="0")]

    decision = decide_start()

    assert decision.may_start
    assert host.asked == 1
    assert "allowing starts" in decision.reason


# --- 1.2 what still pauses ---------------------------------------------------------------


def test_the_weekly_at_seventy_eight_is_refused_naming_the_weekly_figure(host: Host) -> None:
    observed(host, weekly=78.0)

    decision = decide_start()

    assert not decision.may_start
    assert "weekly ~78% estimated (78% read + 0% spent)" in decision.reason
    assert "not 5 points under 80%" in decision.reason


def test_the_session_at_eighty_eight_is_refused_naming_the_session(host: Host) -> None:
    observed(host, session=88.0)

    decision = decide_start()

    assert not decision.may_start
    assert "session ~88%" in decision.reason
    assert "not 5 points under 92%" in decision.reason


def test_one_window_s_room_does_not_offset_the_other(host: Host) -> None:
    observed(host, session=10.0, weekly=77.0)

    decision = decide_start()

    assert not decision.may_start
    assert "weekly ~77%" in decision.reason
    assert "not 5 points under 80%" in decision.reason
    assert "allowing starts" not in decision.reason


# --- 1.4 what was spent since the reading ------------------------------------------------


def seventy(host: Host) -> None:
    """A session at 70% against 92, read three hours ago, and the refusal."""
    keep(host, 3 * HOUR, session=70.0, weekly=6.0)
    refused_ago(host)


def test_one_unit_that_spent_since_the_reading_adds_its_allowance_and_still_allows(
    host: Host,
) -> None:
    seventy(host)
    spent(host, "feature/1", HOUR)

    decision = decide_start(unit="feature/9")

    assert decision.may_start
    assert "session ~80% estimated (70% read + 10% spent)" in decision.reason


def test_two_units_that_spent_since_the_reading_refuse(host: Host) -> None:
    seventy(host)
    spent(host, "feature/1", HOUR)
    spent(host, "feature/2", 30 * MINUTE)

    decision = decide_start(unit="feature/9")

    assert not decision.may_start
    assert "session ~90%" in decision.reason
    assert "not 5 points under 92%" in decision.reason


def test_one_unit_with_four_records_counts_once(host: Host) -> None:
    seventy(host)
    spent(host, "feature/1", 150 * MINUTE, 120 * MINUTE, 90 * MINUTE, 30 * MINUTE)

    decision = decide_start(unit="feature/9")

    assert decision.may_start
    assert "session ~80% estimated (70% read + 10% spent)" in decision.reason


def test_records_before_the_reading_do_not_count(host: Host) -> None:
    seventy(host)
    spent(host, "feature/1", 4 * HOUR)
    spent(host, "feature/2", 200 * MINUTE)

    decision = decide_start(unit="feature/9")

    assert decision.may_start
    assert "session ~70% estimated (70% read + 0% spent)" in decision.reason


def test_a_unit_admitted_on_an_estimate_counts_before_its_record_and_once_after(
    host: Host,
) -> None:
    seventy(host)
    admit(host, "feature/1")

    first = decide_start(unit="feature/1")

    assert first.may_start
    assert "session ~80% estimated (70% read + 10% spent)" in first.reason

    spent(host, "feature/1", 5 * MINUTE)

    second = decide_start(unit="feature/1")

    assert "session ~80% estimated (70% read + 10% spent)" in second.reason


def test_a_unit_that_is_allowed_on_an_estimate_is_recorded_in_the_cache_file(
    host: Host,
) -> None:
    seventy(host)
    admit(host, "feature/1")

    decide_start(unit="feature/2")

    assert admitted(host) == ["feature/1", "feature/2"]


# --- 1.5 a window that has reset since the reading ---------------------------------------


def test_a_session_reset_forty_minutes_ago_starts_from_the_reset_and_the_weekly_keeps_its_figure(
    host: Host,
) -> None:
    """Zero, plus the floor's eight points for forty minutes and the margin of two."""
    keep(host, 2 * HOUR, session=88.0, weekly=65.0, session_resets_in=-40 * MINUTE)
    refused_ago(host)

    decision = decide_start()

    assert decision.may_start
    assert re.search(r"session ~1[01]% estimated", decision.reason)
    assert "88% read" not in decision.reason
    assert "weekly ~65% estimated (65% read + 0% spent)" in decision.reason


def test_a_session_reset_ten_hours_ago_refuses_at_122_points(host: Host) -> None:
    keep(host, 11 * HOUR, session=5.0, weekly=6.0, session_resets_in=-10 * HOUR)
    refused_ago(host)

    decision = decide_start()

    assert not decision.may_start
    assert re.search(r"session ~12[23]%", decision.reason)


def test_a_reading_with_no_open_window_starts_from_zero_with_no_ramp(host: Host) -> None:
    configure(**pause_at(80, usage_pause_ceiling_pct=95))
    keep(host, 3 * HOUR, session=0.0, weekly=60.0)
    kept = json.loads(host.cache.read_text())
    kept["five_hour"]["resets_at"] = None
    host.cache.write_text(json.dumps(kept))
    refused_ago(host)

    decision = decide_start()

    assert decision.may_start
    assert "session ~0% estimated (0% read + 0% spent)" in decision.reason
    assert "ramping" not in decision.reason


# --- 1.6 the cap -------------------------------------------------------------------------


def test_the_fourth_start_on_one_reading_is_refused_until_the_endpoint_may_be_asked(
    host: Host,
) -> None:
    observed(host)

    first_three = [decide_start(unit=f"feature/{n}") for n in (1, 2, 3)]
    fourth = decide_start(unit="feature/4")

    assert all(each.may_start for each in first_three)
    assert not fourth.may_start
    assert re.search(r"(3|three) starts", fourth.reason)
    allowed = next_call_at(host.calls_file, now=datetime.now(UTC))
    assert allowed is not None
    assert fourth.resume_at is not None
    assert abs(fourth.resume_at - allowed) < timedelta(seconds=5)
    assert host.asked == 0


def test_a_good_live_reading_resets_the_count(host: Host) -> None:
    observed(host)
    assert all(decide_start(unit=f"feature/{n}").may_start for n in (1, 2, 3))
    assert admitted(host) == ["feature/1", "feature/2", "feature/3"]
    # The cool-down ends and the interval passes: the endpoint answers.
    host.calls_file.unlink()
    kept = json.loads(host.cache.read_text())
    del kept["cooldown_until"]
    host.cache.write_text(json.dumps(kept))
    host.answers = [payload(session=1.0, weekly=65.0)]

    decision = decide_start(unit="feature/4")

    assert decision.may_start
    assert host.asked == 1
    assert admitted(host) == []


def test_a_cap_of_zero_never_allows_on_an_estimate(host: Host) -> None:
    thresholds(usage_estimate_max_starts=0)
    observed(host)

    decision = decide_start(unit="feature/1")

    assert not decision.may_start
    assert "estimate" in decision.reason.lower()
    assert decision.resume_at is not None


def test_the_count_survives_a_refusal_that_rewrites_the_cache_file(host: Host) -> None:
    keep(host, 89 * MINUTE, session=0.0, weekly=65.0)
    admit(host, "feature/0")
    host.answers = [refusal(retry_after="0")]

    decision = decide_start(unit="feature/1")

    assert decision.may_start
    assert "cooldown_until" in json.loads(host.cache.read_text())
    assert admitted(host) == ["feature/0", "feature/1"]


# --- 1.7 the minimum interval ------------------------------------------------------------


def test_the_estimate_allows_where_the_minimum_interval_would_have_refused_and_makes_no_call(
    host: Host,
) -> None:
    observed(host)
    assert next_call_at(host.calls_file, now=datetime.now(UTC)) is not None

    decision = decide_start()

    assert decision.may_start
    assert host.asked == 0


def test_an_estimate_that_is_not_ample_keeps_the_old_refusal_and_its_message(host: Host) -> None:
    observed(host, weekly=78.0)

    decision = decide_start()

    assert not decision.may_start
    assert "the minimum interval allows the next call at" in decision.reason
    assert decision.resume_at is not None
    assert "weekly ~78%" in decision.reason
    assert host.asked == 0
