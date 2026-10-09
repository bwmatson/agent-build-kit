"""A failed live usage read is absorbed before anything pauses.

The usage endpoint rate-limits, so the guard asks it less: a good answer is
kept for a configured time and answers every reader in every process, a
rate-limit answer starts a cool-down kept beside it, and a call that fails is
retried or covered by the last good reading before the editor's.

Only the endpoint (`urllib.request.urlopen`), the home directory and the
editor's `~/.claude.json` are faked, with what each really holds.
"""

import io
import json
import logging
import urllib.error
from datetime import UTC, datetime, timedelta
from email.message import Message
from pathlib import Path

import pytest

from agent_build_kit import config as config_module
from agent_build_kit.config import CLAUDE_CODE, WorkspaceConfig
from agent_build_kit.pipeline import usage_guard
from agent_build_kit.pipeline.usage_guard import current_usage, may_start_unit
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime


def payload(*, session: float = 14.0, resets_in: timedelta = timedelta(hours=2)) -> dict:
    now = datetime.now(UTC)
    return {
        "five_hour": {"utilization": session, "resets_at": (now + resets_in).isoformat()},
        "seven_day": {
            "utilization": 6.0,
            "resets_at": (now + timedelta(days=3)).isoformat(),
        },
        "extra_usage": {
            "is_enabled": True,
            "monthly_limit": 10000,
            "used_credits": 1324.0,
            "spend_limit_reached": False,
        },
    }


class Response:
    def __init__(self, body: object) -> None:
        self._raw = io.BytesIO(json.dumps(body).encode())

    def __enter__(self) -> "Response":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self, *args: int) -> bytes:
        return self._raw.read(*args)


def too_many_requests(retry_after: str | None = "900") -> urllib.error.HTTPError:
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError(
        usage_guard.USAGE_URL, 429, "Too Many Requests", headers, io.BytesIO(b"")
    )


class Host:
    """The machine: the endpoint's answers in order, a home with no editor
    reading unless a test writes one, and a clock that does not sleep."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.calls = 0
        self.answers: list[object] = []
        self.sleeps: list[float] = []
        self.home = tmp_path / "home"
        self.home.mkdir()
        self.cache = self.home / ".cache" / "agent-build-kit" / "usage-cache.json"
        self.editor = self.home / ".claude.json"
        monkeypatch.setenv("HOME", str(self.home))
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "token")
        monkeypatch.setattr(usage_guard, "CREDENTIALS_PATH", self.home / "no-credentials.json")
        monkeypatch.setattr(usage_guard, "DEFAULT_ANCHOR_PATH", self.editor)
        monkeypatch.setattr("urllib.request.urlopen", self.urlopen)
        monkeypatch.setattr("time.sleep", self.sleeps.append)
        config_module.activate(WorkspaceConfig(), None)

    def urlopen(self, request: object, timeout: float | None = None) -> Response:
        self.calls += 1
        answer = self.answers.pop(0) if self.answers else TimeoutError("timed out")
        if isinstance(answer, BaseException):
            raise answer
        return Response(answer)

    def configure(self, **limits: int) -> None:
        config_module.activate(
            WorkspaceConfig.model_validate({"runtimes": {CLAUDE_CODE: {"limits": limits}}}), None
        )

    def keep_reading(self, age: timedelta, **overrides: object) -> None:
        """A good live reading some process kept `age` ago."""
        self.cache.parent.mkdir(parents=True, exist_ok=True)
        fetched = datetime.now(UTC) - age
        body = {**payload(**overrides), "fetched_at": fetched.isoformat()}  # type: ignore[arg-type]
        self.cache.write_text(json.dumps(body))

    def editor_reading(self, age: timedelta, *, session: int = 20) -> None:
        fetched = datetime.now(UTC) - age
        resets = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
        self.editor.write_text(
            json.dumps(
                {
                    "cachedUsageUtilization": {
                        "fetchedAtMs": int(fetched.timestamp() * 1000),
                        "utilization": {
                            "five_hour": {"utilization": session, "resets_at": resets},
                            "seven_day": {"utilization": 5, "resets_at": resets},
                        },
                    }
                }
            )
        )


@pytest.fixture
def host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Host:
    return Host(tmp_path, monkeypatch)


# --- the cache -------------------------------------------------------------------


def test_a_reading_is_answered_from_the_cache_for_fifteen_minutes(host: Host) -> None:
    host.keep_reading(timedelta(minutes=14))

    reading = current_usage()

    assert host.calls == 0
    assert reading is not None
    assert reading.session_pct == 14


def test_a_reading_older_than_the_cache_time_asks_the_endpoint(host: Host) -> None:
    host.keep_reading(timedelta(minutes=16))
    host.answers = [payload(session=33.0)]

    reading = current_usage()

    assert host.calls == 1
    assert reading is not None
    assert (reading.session_pct, reading.source) == (33, "live")


def test_the_status_command_is_answered_from_the_same_cache(host: Host) -> None:
    host.keep_reading(timedelta(minutes=14))
    runtime = ClaudeCodeRuntime(
        read_live=lambda: usage_guard.read_live_usage(cache_path=host.cache),
        read_cached=usage_guard.read_cached_usage,
    )

    status = runtime.get_usage_status()

    assert host.calls == 0
    assert status is not None
    assert status.session_pct == 14


def test_a_setting_changes_the_cache_time(host: Host) -> None:
    host.configure(usage_cache_minutes=5)
    host.keep_reading(timedelta(minutes=4))
    current_usage()
    assert host.calls == 0

    host.keep_reading(timedelta(minutes=6))
    host.answers = [payload()]
    current_usage()
    assert host.calls == 1

    host.configure(usage_cache_minutes=30)
    host.keep_reading(timedelta(minutes=20))
    current_usage()
    assert host.calls == 1


def test_a_reading_is_not_used_past_its_window_s_reset(host: Host) -> None:
    host.keep_reading(timedelta(minutes=3), resets_in=timedelta(minutes=-1))
    host.answers = [payload(session=2.0)]

    reading = current_usage()

    assert host.calls == 1
    assert reading is not None
    assert reading.session_pct == 2


# --- the cool-down and the retry -------------------------------------------------


@pytest.mark.parametrize("retry_after", ["900", None])
def test_a_rate_limit_answer_is_not_retried_and_starts_a_cool_down(
    host: Host, retry_after: str | None
) -> None:
    host.answers = [too_many_requests(retry_after)]

    first = current_usage()
    second = current_usage()

    assert host.calls == 1
    assert host.sleeps == []
    assert first is None
    assert second is None


def test_the_cool_down_is_kept_for_a_second_process(host: Host) -> None:
    host.keep_reading(timedelta(minutes=20))
    host.answers = [too_many_requests()]
    current_usage()

    # A new process holds nothing but the files.
    host.answers = [payload(session=77.0)]
    reading = current_usage()

    assert host.calls == 1
    assert reading is not None
    assert reading.session_pct == 14


def test_a_timeout_is_retried_once_after_a_delay(host: Host) -> None:
    host.answers = [TimeoutError("timed out"), payload(session=21.0)]

    reading = current_usage()

    assert host.calls == 2
    assert len(host.sleeps) == 1
    assert reading is not None
    assert (reading.session_pct, reading.source) == (21, "live")


def test_a_timeout_that_repeats_is_retried_only_once(host: Host) -> None:
    host.answers = [TimeoutError("timed out"), TimeoutError("timed out")]

    current_usage()

    assert host.calls == 2


def test_a_connection_error_is_retried_once(host: Host) -> None:
    host.answers = [urllib.error.URLError("connection refused"), payload()]

    reading = current_usage()

    assert host.calls == 2
    assert reading is not None


# --- the order of sources --------------------------------------------------------


def test_a_call_that_fails_once_and_then_succeeds_is_used(host: Host) -> None:
    host.editor_reading(timedelta(hours=6))
    host.answers = [OSError("connection reset"), payload(session=25.0)]

    reading = current_usage()

    assert reading is not None
    assert (reading.session_pct, reading.source) == (25, "live")
    assert may_start_unit(reading).may_start


def test_a_failing_call_falls_to_a_good_live_reading_within_the_fallback_age(host: Host) -> None:
    host.keep_reading(timedelta(minutes=20), session=18.0)
    host.editor_reading(timedelta(minutes=1), session=60)
    host.answers = [TimeoutError("timed out"), TimeoutError("timed out")]

    reading = current_usage()

    assert reading is not None
    assert reading.session_pct == 18
    assert reading.source == "cache"
    decision = may_start_unit(reading)
    assert decision.may_start
    assert "cache" in decision.reason


def test_a_failing_call_falls_to_the_editor_past_the_fallback_age(host: Host) -> None:
    host.keep_reading(timedelta(minutes=40), session=18.0)
    host.editor_reading(timedelta(minutes=1), session=60)
    host.answers = [TimeoutError("timed out"), TimeoutError("timed out")]

    reading = current_usage()

    assert reading is not None
    assert (reading.session_pct, reading.source) == (60, "claude.json")


def test_the_fallback_age_is_configurable(host: Host) -> None:
    host.configure(usage_fallback_minutes=60)
    host.keep_reading(timedelta(minutes=40), session=18.0)
    host.editor_reading(timedelta(minutes=1), session=60)
    host.answers = [TimeoutError("timed out"), TimeoutError("timed out")]

    reading = current_usage()

    assert reading is not None
    assert (reading.session_pct, reading.source) == (18, "cache")


def test_nothing_recent_refuses_as_stale_naming_the_editor(host: Host) -> None:
    host.keep_reading(timedelta(minutes=40))
    host.editor_reading(timedelta(hours=6))
    host.answers = [TimeoutError("timed out"), TimeoutError("timed out")]

    reading = current_usage()

    assert reading is not None
    decision = may_start_unit(reading)
    assert not decision.may_start
    assert "stale" in decision.reason.lower()
    assert "claude.json" in decision.reason


# --- the cause is logged, a failure is not a reading -----------------------------


def test_a_rate_limit_answer_logs_its_status_once(
    host: Host, caplog: pytest.LogCaptureFixture
) -> None:
    host.answers = [too_many_requests()]

    with caplog.at_level(logging.WARNING):
        current_usage()
        current_usage()

    assert len([r for r in caplog.records if "429" in r.getMessage()]) == 1


def test_a_repeated_failure_logs_its_exception_name_once(
    host: Host, caplog: pytest.LogCaptureFixture
) -> None:
    host.answers = [TimeoutError("timed out"), TimeoutError("timed out")]

    with caplog.at_level(logging.WARNING):
        current_usage()

    assert len([r for r in caplog.records if "TimeoutError" in r.getMessage()]) == 1


def test_a_failure_is_not_cached_as_a_reading(host: Host) -> None:
    host.answers = [TimeoutError("timed out"), TimeoutError("timed out")]
    assert current_usage() is None
    assert not host.cache.exists()

    host.answers = [payload(session=9.0)]
    reading = current_usage()

    assert host.calls == 3
    assert reading is not None
    assert (reading.session_pct, reading.source) == (9, "live")
