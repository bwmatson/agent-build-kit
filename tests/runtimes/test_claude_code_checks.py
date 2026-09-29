"""What the Claude Code adapter answers without running an agent.

- **`check_policy`** answers locally: the policy hook is registered on every
  policed run and the same commands are denied as flags, so every forbidden
  class is enforced, and proving it costs no agent call.
- **`get_usage_status`** reads the usage window as the usage guard does
  today: the live endpoint first, Claude Code's own cache when that cannot
  answer, and nothing — which pauses — when neither can.

The readings go through `usage_guard`'s real readers, given the endpoint's
JSON and the cache file's contents, so what is faked is only what the
endpoint and the file hold.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path

from agent_build_kit.pipeline.usage_guard import read_cached_usage, read_live_usage
from agent_build_kit.runtimes import UsageStatus
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime
from tests.runtimes.claude_cli import no_agent

# What GET /api/oauth/usage answers, as the /usage panel sees it.
LIVE_RESPONSE = {
    "five_hour": {"utilization": 14.0, "resets_at": "2026-09-28T04:50:00.460447+00:00"},
    "seven_day": {"utilization": 6.0, "resets_at": "2026-10-02T02:00:00.460472+00:00"},
    "seven_day_oauth_apps": None,
    "seven_day_opus": None,
    "extra_usage": {
        "is_enabled": True,
        "monthly_limit": 10000,
        "used_credits": 1324.0,
        "utilization": None,
        "spend_limit_reached": False,
    },
}


def _endpoint(payload: object):
    def fetch(url: str, headers: dict[str, str]) -> object:
        if isinstance(payload, Exception):
            raise payload
        return payload

    return fetch


def _live(tmp_path: Path, payload: object):
    return partial(
        read_live_usage, token="t", fetch=_endpoint(payload), cache_path=tmp_path / "usage.json"
    )


def _claude_json(tmp_path: Path, *, session_pct: float, weekly_pct: float) -> Path:
    """Claude Code's own config file, with the usage it last cached among the
    rest of what it keeps there."""
    fetched = datetime.now(UTC) - timedelta(minutes=5)
    path = tmp_path / ".claude.json"
    path.write_text(
        json.dumps(
            {
                "numStartups": 212,
                "installMethod": "native",
                "autoUpdates": False,
                "hasCompletedOnboarding": True,
                "projects": {},
                "cachedUsageUtilization": {
                    "fetchedAtMs": int(fetched.timestamp() * 1000),
                    "utilization": {
                        "five_hour": {
                            "utilization": session_pct,
                            "resets_at": (fetched + timedelta(hours=3)).isoformat(),
                        },
                        "seven_day": {"utilization": weekly_pct, "resets_at": None},
                        "seven_day_opus": None,
                    },
                },
            }
        )
    )
    return path


def _nothing_cached() -> None:
    return None


def test_every_forbidden_class_is_enforced_without_running_an_agent(tmp_path: Path) -> None:
    runtime = ClaudeCodeRuntime(execute=no_agent, read_live=_nothing_cached)

    report = runtime.check_policy(tmp_path)

    assert report.ok is True
    assert report.unenforced == ()


def test_usage_comes_from_the_live_endpoint_first(tmp_path: Path) -> None:
    cached = _claude_json(tmp_path, session_pct=80, weekly_pct=50)
    runtime = ClaudeCodeRuntime(
        execute=no_agent,
        read_live=_live(tmp_path, LIVE_RESPONSE),
        read_cached=partial(read_cached_usage, cached),
    )

    assert runtime.get_usage_status() == UsageStatus(
        session_pct=14,
        weekly_pct=6,
        resets_at=datetime.fromisoformat("2026-09-28T04:50:00.460447+00:00"),
        source="live",
    )


def test_usage_falls_back_to_claude_code_s_own_cache(tmp_path: Path) -> None:
    """The endpoint is undocumented and may refuse; the cache is what the
    usage guard reads then."""
    cached = _claude_json(tmp_path, session_pct=32.0, weekly_pct=4.0)
    runtime = ClaudeCodeRuntime(
        execute=no_agent,
        read_live=_live(tmp_path, OSError("HTTP Error 429: Too Many Requests")),
        read_cached=partial(read_cached_usage, cached),
    )

    status = runtime.get_usage_status()

    assert status is not None
    assert (status.session_pct, status.weekly_pct, status.source) == (32, 4, "claude.json")
    assert status.resets_at is not None


def test_no_reading_anywhere_is_none(tmp_path: Path) -> None:
    """Which the usage guard reads as unknown, and pauses on — never as room."""
    runtime = ClaudeCodeRuntime(
        execute=no_agent,
        read_live=_live(tmp_path, {"error": {"type": "authentication_error"}}),
        read_cached=partial(read_cached_usage, tmp_path / "missing.json"),
    )

    assert runtime.get_usage_status() is None
