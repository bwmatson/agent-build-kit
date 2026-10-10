"""What is written, when, and what is never written."""

import gzip
import json
from pathlib import Path

import pytest

from agent_build_kit.replay.models import ReplayMode, Rule
from agent_build_kit.replay.store import read_cassettes
from tests.replay.fake_upstream import Answer, FakeUpstream
from tests.replay.proxy import ReplayProxy, SecretInRecording
from tests.replay.support import START, config_for, files, send, stored_text

TEST = "tests/test_unit.py::test_build"


def proxy_for(upstream: FakeUpstream, tmp_path: Path, mode: ReplayMode, **kw) -> ReplayProxy:
    secrets = kw.pop("secrets", ())
    config = config_for(upstream.url, tmp_path / "cassettes", **kw)
    return ReplayProxy(
        config, mode, staging=tmp_path / "staging", secrets=secrets, clock=lambda: START
    )


def test_a_failing_test_leaves_no_cassette_and_a_passing_one_promotes_what_it_staged(
    upstream: FakeUpstream, tmp_path: Path
) -> None:
    cassettes = tmp_path / "cassettes"
    with proxy_for(upstream, tmp_path, ReplayMode.record) as proxy:
        proxy.begin("tests/test_unit.py::test_broken")
        send(proxy, body=b'{"n": 1}')
        send(proxy, body=b'{"n": 2}')
        proxy.finish(passed=False)
        assert files(cassettes) == []

        proxy.begin(TEST)
        send(proxy, body=b'{"n": 3}')
        send(proxy, body=b'{"n": 4}')
        assert files(cassettes) == []
        proxy.finish(passed=True)

    stored = read_cassettes(cassettes)
    assert [(c.test_id, c.call_index) for c in stored] == [(TEST, 0), (TEST, 1)]
    assert len(files(cassettes)) == 2


def test_a_secret_in_a_response_body_fails_the_recording_and_stores_nothing(
    tmp_path: Path,
) -> None:
    def leaking(_seen) -> Answer:
        return Answer(chunks=[b'{"echo": "sk-live-1234"}'])

    with FakeUpstream(leaking) as upstream:
        with proxy_for(upstream, tmp_path, ReplayMode.record, secrets=["sk-live-1234"]) as proxy:
            proxy.begin(TEST)
            send(proxy)
            with pytest.raises(SecretInRecording) as raised:
                proxy.finish(passed=True)

    assert "sk-live-1234" not in str(raised.value)
    assert files(tmp_path / "cassettes") == []


def test_credentials_in_request_headers_are_in_no_file(
    upstream: FakeUpstream, tmp_path: Path
) -> None:
    credentials = {"authorization": "Bearer sk-request-1", "x-api-key": "sk-request-2"}
    with proxy_for(upstream, tmp_path, ReplayMode.record) as proxy:
        proxy.begin(TEST)
        send(proxy, headers={**credentials, "content-type": "application/json"})
        proxy.finish(passed=True)

    assert upstream.seen[0].headers["authorization"] == "Bearer sk-request-1"
    assert files(tmp_path / "cassettes")
    text = stored_text(tmp_path / "cassettes")
    assert "sk-request" not in text
    assert "sk-request" not in "".join(str(path) for path in files(tmp_path / "cassettes"))


def body_in(tmp_prefix: str) -> bytes:
    return json.dumps({"cwd": f"{tmp_prefix}/work", "task": "add a marker"}).encode()


PREFIXES = ("/tmp/pytest-of-user/pytest-1", "/tmp/pytest-of-user/pytest-2")
VOLATILE = Rule(pattern=r"/tmp/pytest-of-\w+/pytest-\d+", placeholder="<TMP>")


def two_runs(upstream: FakeUpstream, tmp_path: Path, rules: list[Rule]) -> ReplayProxy:
    with proxy_for(upstream, tmp_path, ReplayMode.record) as proxy:
        proxy.begin(TEST, rules)
        send(proxy, body=body_in(PREFIXES[0]))
        proxy.finish(passed=True)
    with proxy_for(upstream, tmp_path, ReplayMode.replay) as proxy:
        proxy.begin(TEST, rules)
        send(proxy, body=body_in(PREFIXES[1]))
        proxy.finish(passed=True)
    return proxy


def test_two_requests_differing_in_a_temporary_prefix_miss_without_a_rule(
    upstream: FakeUpstream, tmp_path: Path
) -> None:
    two_runs(upstream, tmp_path, [])
    assert len(upstream.seen) == 2


def test_a_declared_rule_makes_them_hit_and_is_stored_and_reported(
    upstream: FakeUpstream, tmp_path: Path
) -> None:
    proxy = two_runs(upstream, tmp_path, [VOLATILE])

    assert len(upstream.seen) == 1
    assert [c.rules for c in read_cassettes(tmp_path / "cassettes")] == [[VOLATILE]]
    assert proxy.rules_used == [VOLATILE]


def test_a_streamed_response_is_stored_and_replayed_as_its_chunks_in_order(
    tmp_path: Path,
) -> None:
    chunks = [b"data: one\n\n", b"data: two\n\n", b"data: three\n\n"]
    with FakeUpstream(lambda _seen: Answer(chunks=chunks)) as upstream:
        with proxy_for(upstream, tmp_path, ReplayMode.record) as proxy:
            proxy.begin(TEST)
            send(proxy)
            proxy.finish(passed=True)
        assert [c.response.chunks for c in read_cassettes(tmp_path / "cassettes")] == [chunks]

        with proxy_for(upstream, tmp_path, ReplayMode.replay) as proxy:
            proxy.begin(TEST)
            reply = send(proxy)
            proxy.finish(passed=True)

        assert len(upstream.seen) == 1
        assert reply.raw == b"".join(chunks)


def test_an_oversized_body_is_not_recorded_and_is_reported(
    upstream: FakeUpstream, tmp_path: Path
) -> None:
    with FakeUpstream(lambda _seen: Answer(chunks=[b"0123456789"])) as large:
        with proxy_for(large, tmp_path, ReplayMode.record, max_body_bytes=5) as proxy:
            proxy.begin(TEST)
            reply = send(proxy)
            proxy.finish(passed=True)
        assert reply.raw == b"0123456789"
        assert files(tmp_path / "cassettes") == []
        assert len(proxy.too_large) == 1

        with proxy_for(large, tmp_path, ReplayMode.replay, max_body_bytes=5) as proxy:
            proxy.begin(TEST)
            send(proxy)
            proxy.finish(passed=True)
        assert len(large.seen) == 2


def test_a_gzip_encoded_body_is_replayed_byte_for_byte(tmp_path: Path) -> None:
    compressed = gzip.compress(b"payload " * 100)
    answer = Answer(headers={"Content-Encoding": "gzip"}, chunks=[compressed])
    with FakeUpstream(lambda _seen: answer) as upstream:
        for mode in (ReplayMode.record, ReplayMode.replay):
            with proxy_for(upstream, tmp_path, mode) as proxy:
                proxy.begin(TEST)
                reply = send(proxy)
                proxy.finish(passed=True)
            assert reply.raw == compressed
            assert reply.headers["content-encoding"] == "gzip"
        assert len(upstream.seen) == 1
