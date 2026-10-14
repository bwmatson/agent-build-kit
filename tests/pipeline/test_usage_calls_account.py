"""Each line of the usage call record names the account in use (spec: usage-account).

The line a call, a cache hit and a `claude-json` decision write carries the account directory
(null for the default); the rate and the cache interval still read every line, whatever its
account, and a line written before the field existed reads with none.
"""

import json
from datetime import UTC, datetime, timedelta

from agent_build_kit.pipeline.usage_calls import (
    CLAUDE_JSON,
    UsageCall,
    derive_rate,
    parse_calls,
)
from agent_build_kit.pipeline.usage_guard import current_usage, decide_start, read_live_usage
from agent_build_kit.settings import settings
from tests.usage_host import Host, configure, editor_block, pause_at, payload

MINUTE = timedelta(minutes=1)
HOUR = timedelta(hours=1)

OLD_LINE = {
    "at": (datetime.now(UTC) - timedelta(minutes=30)).isoformat(),
    "caller": "guard",
    "outcome": "ok",
    "status": 200,
    "latency_ms": 90,
    "headers": {},
}


def test_a_call_a_cache_hit_and_a_claude_json_decision_each_record_the_account(
    host: Host,
) -> None:
    account = host.use_account(block=editor_block(6 * MINUTE, session=33, resets_in=2 * HOUR))
    host.answers = [payload(session=90.0)]
    read_live_usage()
    current_usage()
    kept = json.loads(host.cache.read_text())
    kept["fetched_at"] = (datetime.now(UTC) - 40 * MINUTE).isoformat()
    host.cache.write_text(json.dumps(kept))
    configure(**pause_at(92))
    decide_start()

    outcomes = {each["outcome"]: each["account"] for each in host.lines()}

    assert set(outcomes) >= {"ok", "cache", CLAUDE_JSON}
    assert set(outcomes.values()) == {str(account)}


def test_the_rate_counts_the_lines_of_every_account_and_an_old_line_has_none(host: Host) -> None:
    host.seed(OLD_LINE)
    for name in ("a", None, "b"):
        host.monkeypatch.setattr(settings, "claude_home", host.home / name if name else None)
        host.answers = [payload()]
        read_live_usage()

    calls = parse_calls(host.calls_file.read_text())
    rate = derive_rate(calls, now=datetime.now(UTC))

    assert [each.account for each in calls] == [
        None,
        str(host.home / "a"),
        None,
        str(host.home / "b"),
    ]
    assert all("account" in each for each in host.lines()[1:])
    assert isinstance(calls[0], UsageCall)
    assert rate.day.calls == 4
