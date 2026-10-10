"""Every use of the usage endpoint is recorded, and the call rate is read from it.

The endpoint rate-limits and does not say how often it allows calls, so each
call and each answer from the cache is kept in a local record (`usage-calls.jsonl`
in the state directory), the rate is derived from it, printed by the status
command and exported (spec: usage-pause).

Only the endpoint (`urllib.request.urlopen`) and the home directory are faked,
with the answers the endpoint really gives, headers included.
"""

import argparse
import io
import json
import subprocess
import urllib.error
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from email.message import Message
from importlib import resources
from pathlib import Path

import pytest

from agent_build_kit import config as config_module
from agent_build_kit import telemetry
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.config import CLAUDE_CODE, WorkspaceConfig
from agent_build_kit.pipeline import archive, usage_guard
from agent_build_kit.pipeline.usage_calls import (
    CALLS_NAME,
    UsageCall,
    derive_rate,
    rate_line,
    read_calls,
)
from agent_build_kit.pipeline.usage_guard import current_usage, read_live_usage
from agent_build_kit.runtimes import claude_code
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime
from agent_build_kit.serve.metrics import LocalSource, catalogue, metrics_page
from agent_build_kit.tracks import runner as tracks_runner
from tests.conftest import make_installation
from tests.factories import stored_unit
from tests.otlp import Collector, enabled

SECRET = "sk-ant-oat01-the-secret"
NOW = datetime(2030, 1, 2, 12, 0, tzinfo=UTC)


def payload() -> dict:
    now = datetime.now(UTC)
    return {
        "five_hour": {"utilization": 14.0, "resets_at": (now + timedelta(hours=2)).isoformat()},
        "seven_day": {"utilization": 6.0, "resets_at": (now + timedelta(days=3)).isoformat()},
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


def refusal(**headers: str) -> urllib.error.HTTPError:
    message = Message()
    for name, value in headers.items():
        message[name.replace("_", "-")] = value
    return urllib.error.HTTPError(
        usage_guard.USAGE_URL, 429, "Too Many Requests", message, io.BytesIO(b"")
    )


def server_error() -> urllib.error.HTTPError:
    message = Message()
    message["Content-Type"] = "application/json"
    return urllib.error.HTTPError(
        usage_guard.USAGE_URL, 500, "Internal Server Error", message, io.BytesIO(b"")
    )


class Host:
    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.answers: list[object] = []
        self.home = tmp_path / "home"
        self.home.mkdir()
        self.cache = self.home / ".cache" / "agent-build-kit" / "usage-cache.json"
        self.calls_file = self.cache.parent / CALLS_NAME
        monkeypatch.setenv("HOME", str(self.home))
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", SECRET)
        monkeypatch.setattr(usage_guard, "CREDENTIALS_PATH", self.home / "no-credentials.json")
        monkeypatch.setattr(usage_guard, "DEFAULT_ANCHOR_PATH", self.home / ".claude.json")
        monkeypatch.setattr("urllib.request.urlopen", self.urlopen)
        monkeypatch.setattr("time.sleep", lambda _: None)
        config_module.activate(WorkspaceConfig(), None)
        usage_guard.forget_logged_failures()

    def urlopen(self, request: object, timeout: float | None = None) -> Response:
        answer = self.answers.pop(0) if self.answers else TimeoutError("timed out")
        if isinstance(answer, BaseException):
            raise answer
        return Response(answer)

    def keep_reading(self, age: timedelta) -> None:
        self.cache.parent.mkdir(parents=True, exist_ok=True)
        fetched = datetime.now(UTC) - age
        self.cache.write_text(json.dumps({**payload(), "fetched_at": fetched.isoformat()}))

    def lines(self) -> list[dict]:
        if not self.calls_file.exists():
            return []
        return [json.loads(line) for line in self.calls_file.read_text().splitlines() if line]

    def seed(self, *lines: dict) -> None:
        self.calls_file.parent.mkdir(parents=True, exist_ok=True)
        self.calls_file.write_text("".join(json.dumps(each) + "\n" for each in lines))


@pytest.fixture
def host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Host:
    return Host(tmp_path, monkeypatch)


def line(
    at: datetime,
    outcome: str = "ok",
    caller: str = "guard",
    *,
    status: int | None = None,
    age_seconds: int | None = None,
    headers: dict[str, str] | None = None,
) -> dict:
    return {
        "at": at.isoformat(),
        "caller": caller,
        "outcome": outcome,
        "status": status if status is not None else (200 if outcome == "ok" else None),
        "latency_ms": 120,
        "headers": headers or {},
        "age_seconds": age_seconds,
    }


def ago(**delta: float) -> datetime:
    return NOW - timedelta(**delta)


def calls_of(*lines: dict) -> list[UsageCall]:
    return [UsageCall.model_validate(each) for each in lines]


# --- the record ------------------------------------------------------------------


def test_a_call_appends_a_line_with_time_caller_outcome_status_and_latency(host: Host) -> None:
    host.answers = [payload()]
    before = datetime.now(UTC)

    read_live_usage()

    (written,) = host.lines()
    assert written["outcome"] == "ok"
    assert written["caller"] == "guard"
    assert written["status"] == 200
    assert isinstance(written["latency_ms"], int)
    assert written["latency_ms"] >= 0
    assert before <= datetime.fromisoformat(written["at"]) <= datetime.now(UTC)


def test_a_refusal_keeps_its_rate_limit_and_retry_headers(host: Host) -> None:
    host.answers = [
        refusal(
            Retry_After="900",
            anthropic_ratelimit_requests_remaining="0",
            X_RateLimit_Reset="2030-01-01T09:15:00Z",
            Content_Type="application/json",
            Authorization=f"Bearer {SECRET}",
        )
    ]

    read_live_usage()

    (written,) = host.lines()
    assert (written["outcome"], written["status"]) == ("rate_limited", 429)
    kept = {name.lower(): value for name, value in written["headers"].items()}
    assert kept["retry-after"] == "900"
    assert kept["anthropic-ratelimit-requests-remaining"] == "0"
    assert kept["x-ratelimit-reset"] == "2030-01-01T09:15:00Z"
    assert "content-type" not in kept
    assert "authorization" not in kept


def test_a_timeout_and_an_error_are_each_recorded(host: Host) -> None:
    host.answers = [TimeoutError("timed out"), TimeoutError("timed out")]
    read_live_usage()
    assert host.lines()
    assert {each["outcome"] for each in host.lines()} == {"timeout"}
    assert all(each["status"] is None for each in host.lines())

    host.seed()
    host.answers = [server_error()]
    read_live_usage()
    (written,) = host.lines()
    assert (written["outcome"], written["status"]) == ("error", 500)


def test_a_reading_answered_from_the_cache_is_recorded_with_its_age(host: Host) -> None:
    host.keep_reading(timedelta(minutes=14))

    current_usage()

    (written,) = host.lines()
    assert written["outcome"] == "cache"
    assert written["caller"] == "guard"
    assert 14 * 60 - 5 <= written["age_seconds"] <= 14 * 60 + 30


def test_no_line_holds_a_token(host: Host) -> None:
    host.answers = [refusal(Retry_After="900", Authorization=f"Bearer {SECRET}"), payload()]
    read_live_usage(token=SECRET)
    host.cache.unlink()
    read_live_usage(token=SECRET)

    text = host.calls_file.read_text()
    assert text
    assert SECRET not in text


def test_lines_older_than_a_week_are_dropped(host: Host) -> None:
    now = datetime.now(UTC)
    host.seed(line(now - timedelta(days=8)), line(now - timedelta(days=6)))
    host.answers = [payload()]

    read_live_usage()

    kept = sorted(datetime.fromisoformat(each["at"]) for each in host.lines())
    assert len(kept) == 2
    assert kept[0] > now - timedelta(days=7)


def test_archiving_a_change_leaves_the_record(host: Host, tmp_path: Path) -> None:
    host.answers = [payload()]
    read_live_usage()
    planning = tmp_path / "planning"
    change = planning / "openspec" / "changes" / "add-marker"
    change.mkdir(parents=True)
    (change / "tasks.md").write_text("# Tasks\n")
    before = host.calls_file.read_text()
    assert before

    def run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(args, 0, "", "")

    archived = archive.archive_ready_changes(
        [stored_unit("add-marker/1", change="add-marker", state="merged")],
        planning_repo=planning,
        run=run,
        usage_ledger=host.calls_file.parent / "usage-ledger.jsonl",
    )

    assert archived == ["add-marker"]
    assert host.calls_file.read_text() == before


def test_the_runtime_s_usage_status_is_recorded_under_its_own_caller(
    host: Host, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The adapter's own default reader is what is under test, so the suite's
    # refusal of it is lifted; the endpoint and the home directory are still faked.
    monkeypatch.setattr(claude_code, "read_live_usage", usage_guard.read_live_usage)
    host.keep_reading(timedelta(minutes=3))

    ClaudeCodeRuntime(read_cached=usage_guard.read_cached_usage).get_usage_status()

    assert [each["caller"] for each in host.lines()] == ["status"]


def test_the_tracks_runner_is_recorded_under_its_own_caller(host: Host) -> None:
    host.keep_reading(timedelta(minutes=3))

    tracks_runner.has_headroom()

    assert [each["caller"] for each in host.lines()] == ["tracks"]


def test_the_template_ignores_the_record() -> None:
    template = resources.files("agent_build_kit").joinpath("templates/gitignore").read_text()

    assert f"runs/{CALLS_NAME}" in template.splitlines()


def test_a_missing_or_damaged_record_reads_as_empty(tmp_path: Path) -> None:
    path = tmp_path / CALLS_NAME
    assert read_calls(path) == []
    path.write_text("not json\n" + json.dumps(line(NOW)) + "\n")

    assert len(read_calls(path)) == 1


# --- the reading -----------------------------------------------------------------


def test_the_reading_counts_calls_by_outcome_and_caller_over_the_hour_and_the_day() -> None:
    calls = calls_of(
        line(ago(hours=23)),
        line(ago(hours=3), caller="status"),
        line(ago(minutes=50), caller="status"),
        line(ago(minutes=40), "cache", age_seconds=600),
        line(ago(minutes=30)),
        line(ago(minutes=25), caller="tracks"),
        line(ago(minutes=20), "rate_limited", status=429),
        line(ago(minutes=10), "timeout"),
    )

    rate = derive_rate(calls, now=NOW)

    assert rate.hour.calls == 6
    assert rate.hour.by_outcome == {"ok": 3, "cache": 1, "rate_limited": 1, "timeout": 1}
    assert rate.hour.by_caller == {"guard": 4, "status": 1, "tracks": 1}
    assert rate.hour.cache_share == pytest.approx(1 / 6)
    assert rate.day.calls == 8
    assert rate.day.by_outcome == {"ok": 5, "cache": 1, "rate_limited": 1, "timeout": 1}
    assert rate.day.by_caller == {"guard": 5, "status": 2, "tracks": 1}
    assert rate.day.cache_share == pytest.approx(1 / 8)


def test_a_refusal_after_many_calls_shows_the_calls_before_it_and_the_quiet_before_it() -> None:
    calls = calls_of(
        *[line(ago(minutes=minutes)) for minutes in (40, 38, 36, 34, 32, 30)],
        line(ago(minutes=28), "rate_limited", status=429),
    )

    rate = derive_rate(calls, now=NOW)

    (refused,) = rate.hour.refusals
    assert refused.at == ago(minutes=28)
    assert refused.quiet_seconds == 120
    assert refused.calls_before == 6
    assert rate.day.refusals == rate.hour.refusals
    assert rate.last_refusal_at == ago(minutes=28)


def test_a_day_without_refusals_gives_none_and_the_shortest_interval_used() -> None:
    calls = calls_of(
        line(ago(hours=10)),
        line(ago(hours=9)),
        line(ago(hours=8, minutes=30)),
        line(ago(hours=8), "cache", age_seconds=100),
        line(ago(hours=2)),
    )

    rate = derive_rate(calls, now=NOW)

    assert rate.day.refusals == ()
    assert rate.hour.refusals == ()
    assert rate.last_refusal_at is None
    assert rate.safe_interval_seconds == 30 * 60


def test_an_interval_followed_by_a_refusal_is_not_a_safe_one() -> None:
    calls = calls_of(
        line(ago(hours=5)),
        line(ago(hours=4, minutes=58)),
        line(ago(hours=4, minutes=57), "rate_limited", status=429),
        line(ago(hours=3)),
        line(ago(hours=2)),
        line(ago(hours=1, minutes=50)),
    )

    rate = derive_rate(calls, now=NOW)

    assert rate.safe_interval_seconds == 600


def test_nothing_recorded_reads_as_no_calls() -> None:
    rate = derive_rate([], now=NOW)

    assert rate.hour.calls == 0
    assert rate.hour.cache_share == 0
    assert rate.safe_interval_seconds is None
    assert rate.last_refusal_at is None


# --- the status line and the metric ----------------------------------------------

STATUS_LINE = "usage calls: 5 in the last hour, 1 refused, 20% from the cache, safe interval 600s"


def hour_of_calls(now: datetime) -> list[dict]:
    return [
        line(now - timedelta(minutes=50)),
        line(now - timedelta(minutes=40)),
        line(now - timedelta(minutes=30), "cache", age_seconds=60),
        line(now - timedelta(minutes=20)),
        line(now - timedelta(minutes=5), "rate_limited", status=429),
    ]


def test_the_status_line_gives_the_hour_the_refusals_the_cache_share_and_the_interval() -> None:
    rate = derive_rate(calls_of(*hour_of_calls(NOW)), now=NOW)

    assert rate_line(rate) == STATUS_LINE
    assert rate_line(derive_rate([], now=NOW)) == (
        "usage calls: 0 in the last hour, 0 refused, 0% from the cache, safe interval none"
    )


def test_the_status_command_prints_the_line_from_the_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = make_installation(tmp_path, planning={"state_dir": "."})
    inst.state_dir.mkdir(parents=True, exist_ok=True)
    (inst.state_dir / CALLS_NAME).write_text(
        "".join(json.dumps(each) + "\n" for each in hour_of_calls(datetime.now(UTC)))
    )
    monkeypatch.setattr(cli, "current_usage", lambda *a, **k: None)

    assert cli.cmd_status(argparse.Namespace(), inst) == 0

    shown = [text for text in capsys.readouterr().out.splitlines() if "usage calls:" in text]
    assert len(shown) == 1
    assert STATUS_LINE in shown[0]


@pytest.fixture
def exported() -> Iterator[Collector]:
    with enabled() as collector:
        assert telemetry.init() is True
        yield collector


def test_calls_are_exported_as_a_counter_by_outcome_and_caller(
    host: Host, exported: Collector
) -> None:
    host.answers = [payload(), refusal(Retry_After="900")]
    read_live_usage()
    host.cache.unlink()
    read_live_usage()
    host.keep_reading(timedelta(minutes=2))
    read_live_usage(caller="status")
    telemetry.shutdown()

    counted = {
        (p.attributes["outcome"], p.attributes["caller"]): p.value
        for p in exported.metric("abk.usage.calls")
    }
    assert counted == {("ok", "guard"): 1, ("rate_limited", "guard"): 1, ("cache", "status"): 1}


def test_the_interval_is_exported_as_a_gauge_of_whole_seconds(
    host: Host, exported: Collector
) -> None:
    now = datetime.now(UTC)
    host.seed(line(now - timedelta(hours=2)), line(now - timedelta(hours=1, minutes=50)))
    host.answers = [payload()]

    read_live_usage()
    telemetry.shutdown()

    (gauge,) = exported.metric("abk.usage.safe_interval")
    assert gauge.value == 600


def test_the_figures_are_shown_from_the_record_when_the_metrics_store_is_not_available(
    tmp_path: Path,
) -> None:
    record = tmp_path / CALLS_NAME
    day = NOW.replace(hour=1)
    record.write_text(
        "".join(
            json.dumps(each) + "\n"
            for each in (
                line(day),
                line(day + timedelta(minutes=10)),
                line(day + timedelta(minutes=12), "rate_limited", status=429),
            )
        )
    )
    local = LocalSource(tmp_path / "ledger.jsonl", calls=record, now=lambda: NOW)
    instruments = {each.name: each for each in catalogue()}

    series = local.series(instruments["abk.usage.calls"])
    interval = local.series(instruments["abk.usage.safe_interval"])

    totals = {
        (s.labels["outcome"], s.labels["caller"]): sum(v for _, v in s.points) for s in series
    }
    assert totals == {("ok", "guard"): 2, ("rate_limited", "guard"): 1}
    assert [v for s in interval for _, v in s.points] == [600]


def test_the_metrics_page_draws_the_call_record_when_the_store_is_down(tmp_path: Path) -> None:
    day = datetime.now(UTC) - timedelta(hours=3)
    (tmp_path / CALLS_NAME).write_text(
        "".join(
            json.dumps(each) + "\n"
            for each in (
                line(day),
                line(day + timedelta(minutes=10)),
                line(day + timedelta(minutes=12), "rate_limited", status=429),
            )
        )
    )

    page = metrics_page("", "", tmp_path / "usage-ledger.jsonl", [], None, "abk")

    by_name = {each["name"]: each for each in page["metrics"]}
    totals = {
        (s["labels"]["outcome"], s["labels"]["caller"]): sum(p[1] for p in s["points"])
        for s in by_name["abk.usage.calls"]["series"]
    }
    assert page["source"] == "local"
    assert totals == {("ok", "guard"): 2, ("rate_limited", "guard"): 1}
    assert by_name["abk.usage.safe_interval"]["series"]


def test_a_refused_connection_is_an_error_not_a_timeout(host: Host) -> None:
    host.answers = [urllib.error.URLError(ConnectionRefusedError())] * 2

    read_live_usage()

    assert {each["outcome"] for each in host.lines()} == {"error"}


def test_a_url_error_caused_by_a_timeout_is_a_timeout(host: Host) -> None:
    host.answers = [urllib.error.URLError(TimeoutError("timed out"))] * 2

    read_live_usage()

    assert {each["outcome"] for each in host.lines()} == {"timeout"}


def test_a_refusal_after_a_failed_call_still_makes_the_interval_unsafe() -> None:
    calls = calls_of(
        line(ago(hours=3)),
        line(ago(hours=2, minutes=50)),
        line(ago(hours=2, minutes=50, seconds=-20), "timeout"),
        line(ago(hours=2, minutes=50, seconds=-40), "rate_limited", status=429),
        line(ago(hours=1, minutes=30)),
        line(ago(minutes=10)),
    )

    assert derive_rate(calls, now=NOW).safe_interval_seconds == 80 * 60


# --- the interval adapts ---------------------------------------------------------


def since(**delta: float) -> datetime:
    return datetime.now(UTC) - timedelta(**delta)


def configure(**limits: int) -> None:
    config_module.activate(
        WorkspaceConfig.model_validate({"runtimes": {CLAUDE_CODE: {"limits": limits}}}), None
    )


def asks_the_endpoint(host: Host, age: timedelta) -> bool:
    """Whether a reading kept `age` ago is asked for again, given the record."""
    host.keep_reading(age)
    host.answers = [payload()]
    read_live_usage()
    return not host.answers


def test_a_refusal_doubles_the_time_a_reading_is_kept(host: Host) -> None:
    host.seed(line(since(minutes=1), "rate_limited", status=429))

    assert not asks_the_endpoint(host, timedelta(minutes=20))
    assert asks_the_endpoint(host, timedelta(minutes=31))


def test_a_second_refusal_doubles_it_again_up_to_the_maximum(host: Host) -> None:
    host.seed(
        line(since(minutes=3), "rate_limited", status=429),
        line(since(minutes=1), "rate_limited", status=429),
    )

    assert not asks_the_endpoint(host, timedelta(minutes=45))
    assert asks_the_endpoint(host, timedelta(minutes=61))


def test_the_time_never_passes_the_configured_maximum(host: Host) -> None:
    configure(usage_cache_max_minutes=40)
    host.seed(
        line(since(minutes=5), "rate_limited", status=429),
        line(since(minutes=3), "rate_limited", status=429),
        line(since(minutes=1), "rate_limited", status=429),
    )

    assert not asks_the_endpoint(host, timedelta(minutes=35))
    assert asks_the_endpoint(host, timedelta(minutes=41))


def test_a_refusal_that_names_a_longer_retry_time_is_respected(host: Host) -> None:
    host.seed(line(since(minutes=1), "rate_limited", status=429, headers={"retry-after": "3600"}))

    assert not asks_the_endpoint(host, timedelta(minutes=45))


def test_a_retry_time_shorter_than_the_doubled_time_changes_nothing(host: Host) -> None:
    host.seed(line(since(minutes=1), "rate_limited", status=429, headers={"retry-after": "60"}))

    assert not asks_the_endpoint(host, timedelta(minutes=20))
    assert asks_the_endpoint(host, timedelta(minutes=31))


def test_the_same_time_without_a_refusal_halves_it(host: Host) -> None:
    host.seed(line(since(minutes=31), "rate_limited", status=429))

    assert asks_the_endpoint(host, timedelta(minutes=16))


def test_a_time_at_the_maximum_halves_once_after_one_quiet(host: Host) -> None:
    host.seed(
        line(since(minutes=67), "rate_limited", status=429),
        line(since(minutes=65), "rate_limited", status=429),
    )

    assert not asks_the_endpoint(host, timedelta(minutes=20))
    assert asks_the_endpoint(host, timedelta(minutes=31))


def test_the_time_never_falls_below_the_configured_value(host: Host) -> None:
    host.seed(line(since(hours=5), "rate_limited", status=429))

    assert not asks_the_endpoint(host, timedelta(minutes=10))
    assert asks_the_endpoint(host, timedelta(minutes=16))


def test_the_configured_value_is_the_start_when_nothing_was_refused(host: Host) -> None:
    configure(usage_cache_minutes=5)
    host.seed(line(since(minutes=10)))

    assert not asks_the_endpoint(host, timedelta(minutes=4))
    assert asks_the_endpoint(host, timedelta(minutes=6))


def status_lines(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *calls: dict) -> list[str]:
    inst = make_installation(tmp_path, planning={"state_dir": "."})
    inst.state_dir.mkdir(parents=True, exist_ok=True)
    (inst.state_dir / CALLS_NAME).write_text("".join(json.dumps(each) + "\n" for each in calls))
    monkeypatch.setattr(cli, "current_usage", lambda *a, **k: None)
    messages: list[str] = []
    monkeypatch.setattr(cli, "log", messages.append)
    assert cli.cmd_status(argparse.Namespace(), inst) == 0
    return [each for each in messages if "usage cache" in each]


def test_the_status_command_says_the_interval_followed_a_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shown = status_lines(tmp_path, monkeypatch, line(since(minutes=5), "rate_limited", status=429))

    assert len(shown) == 1
    assert "30 minutes" in shown[0]
    assert "refusal" in shown[0]


def test_the_status_command_says_the_interval_fell_after_a_quiet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shown = status_lines(tmp_path, monkeypatch, line(since(minutes=40), "rate_limited", status=429))

    assert len(shown) == 1
    assert "15 minutes" in shown[0]
    assert "quiet" in shown[0]


def test_the_status_command_says_when_the_interval_is_the_configured_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shown = status_lines(tmp_path, monkeypatch, line(since(minutes=10)))

    assert len(shown) == 1
    assert "15 minutes" in shown[0]
    assert "configured" in shown[0]
