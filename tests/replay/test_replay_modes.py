"""What each mode does with a call, and when a recording is too old to answer one."""

import json
import threading
from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_build_kit.replay.models import ReplayMode, UpstreamKind
from agent_build_kit.replay.store import read_cassettes
from agent_build_kit.settings import Settings
from tests.replay.fake_upstream import FakeUpstream
from tests.replay.proxy import ReplayProxy
from tests.replay.support import ENV, START, config_for, send

TEST = "tests/test_unit.py::test_build"


def body(model: str = "m-1", text: str = "hi") -> bytes:
    return json.dumps({"model": model, "messages": [{"role": "user", "content": text}]}).encode()


def proxy_for(
    upstream: FakeUpstream, tmp_path: Path, mode: ReplayMode, *, clock=lambda: START, **kw
) -> ReplayProxy:
    config = config_for(upstream.url, tmp_path / "cassettes", **kw)
    return ReplayProxy(config, mode, staging=tmp_path / "staging", clock=clock)


def passing_run(proxy: ReplayProxy, *calls: dict) -> None:
    proxy.begin(TEST)
    for call in calls:
        send(proxy, **call)
    proxy.finish(passed=True)


def recorded(upstream: FakeUpstream, tmp_path: Path, *calls: dict, **kw) -> None:
    with proxy_for(upstream, tmp_path, ReplayMode.record, **kw) as proxy:
        passing_run(proxy, *calls)


def test_an_identical_request_replays_without_calling_the_upstream(
    upstream: FakeUpstream, tmp_path: Path
) -> None:
    call = {"body": body()}
    recorded(upstream, tmp_path, call)
    assert len(upstream.seen) == 1

    with proxy_for(upstream, tmp_path, ReplayMode.replay) as proxy:
        proxy.begin(TEST)
        reply = send(proxy, **call)
        proxy.finish(passed=True)

    assert reply.raw == b"echo:" + body()
    assert len(upstream.seen) == 1


@pytest.mark.parametrize(
    "different",
    [
        {"body": body(text="ho")},
        {"body": body(model="m-2")},
        {"body": body(), "query": "page=2"},
        {"body": body(), "path": "/v1/other"},
    ],
    ids=["body", "model", "query", "path"],
)
def test_a_different_request_goes_live_and_is_recorded_under_its_own_key(
    upstream: FakeUpstream, tmp_path: Path, different: dict
) -> None:
    recorded(upstream, tmp_path, {"body": body()})

    with proxy_for(upstream, tmp_path, ReplayMode.replay) as proxy:
        passing_run(proxy, different)

    assert len(upstream.seen) == 2
    assert len({cassette.key for cassette in read_cassettes(tmp_path / "cassettes")}) == 2


@pytest.mark.parametrize(
    ("kind", "limit", "age_days", "answered"),
    [
        (UpstreamKind.deterministic, "max_age_days", 2, True),
        (UpstreamKind.deterministic, "max_age_days", 4, False),
        (UpstreamKind.llm, "llm_max_age_days", 2, True),
        (UpstreamKind.llm, "llm_max_age_days", 4, False),
    ],
)
def test_a_cassette_answers_only_while_younger_than_the_age_in_the_config(
    upstream: FakeUpstream,
    tmp_path: Path,
    kind: UpstreamKind,
    limit: str,
    age_days: int,
    answered: bool,
) -> None:
    ages = {limit: 3}
    recorded(upstream, tmp_path, {"body": body()}, kind=kind, **ages)
    later = START + timedelta(days=age_days)

    with proxy_for(
        upstream, tmp_path, ReplayMode.replay, clock=lambda: later, kind=kind, **ages
    ) as proxy:
        passing_run(proxy, {"body": body()})

    assert len(upstream.seen) == (1 if answered else 2)
    stored = read_cassettes(tmp_path / "cassettes")
    assert [cassette.recorded_at for cassette in stored] == [START if answered else later]


def test_off_starts_no_listener_and_changes_no_environment(
    upstream: FakeUpstream, tmp_path: Path
) -> None:
    threads = threading.active_count()
    with proxy_for(upstream, tmp_path, ReplayMode.off) as proxy:
        assert proxy.addresses == {}
        assert proxy.environment() == {}
        assert threading.active_count() == threads
    assert upstream.seen == []


def test_the_mode_is_the_replay_mode_setting_and_an_unknown_one_is_refused(
    monkeypatch: pytest.MonkeyPatch, upstream: FakeUpstream, tmp_path: Path
) -> None:
    assert Settings(_env_file=None).replay_mode is ReplayMode.off
    monkeypatch.setenv("ABK_REPLAY_MODE", "replay")
    mode = Settings(_env_file=None).replay_mode
    assert mode is ReplayMode.replay
    monkeypatch.setenv("ABK_REPLAY_MODE", "sometimes")
    with pytest.raises(ValidationError, match="replay_mode"):
        Settings(_env_file=None)

    with proxy_for(upstream, tmp_path, mode) as proxy:
        assert set(proxy.environment()) == {ENV}


def test_record_goes_live_every_time_and_writes_after_a_pass(
    upstream: FakeUpstream, tmp_path: Path
) -> None:
    recorded(upstream, tmp_path, {"body": body()})
    recorded(upstream, tmp_path, {"body": body()})
    assert len(upstream.seen) == 2


def test_live_ignores_the_cassette_and_writes_the_new_answer_after_a_pass(
    upstream: FakeUpstream, tmp_path: Path
) -> None:
    recorded(upstream, tmp_path, {"body": body()})
    later = START + timedelta(days=1)

    with proxy_for(upstream, tmp_path, ReplayMode.live, clock=lambda: later) as proxy:
        passing_run(proxy, {"body": body()})

    assert len(upstream.seen) == 2
    assert [c.recorded_at for c in read_cassettes(tmp_path / "cassettes")] == [later]
