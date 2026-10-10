"""What the proxy does that a client of the real upstream would notice."""

import gzip
import http.client
import os
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from agent_build_kit.config import ReplayConfig, ReplayUpstream
from agent_build_kit.replay.models import ReplayMode, UpstreamKind
from agent_build_kit.replay.store import read_cassettes
from tests.replay.fake_upstream import Answer, FakeUpstream, Seen
from tests.replay.proxy import ReplayProxy, SecretInRecording
from tests.replay.support import UPSTREAM, config_for, files, refused_url, send
from tests.waiting import wait_for

TEST = "tests/test_unit.py::test_build"
START = datetime(2030, 1, 1, tzinfo=UTC)


def proxy_for(config: ReplayConfig, tmp_path: Path, mode: ReplayMode, **kw) -> ReplayProxy:
    return ReplayProxy(config, mode, staging=tmp_path / "staging", clock=lambda: START, **kw)


def connect(proxy: ReplayProxy) -> http.client.HTTPConnection:
    address = urlsplit(proxy.addresses[UPSTREAM])
    assert address.hostname is not None
    return http.client.HTTPConnection(address.hostname, address.port)


def test_two_upstreams_given_the_same_request_each_replay_their_own_answer(
    tmp_path: Path,
) -> None:
    def named(name: str) -> FakeUpstream:
        return FakeUpstream(lambda _seen: Answer(chunks=[name.encode()]))

    with named("from-a") as first, named("from-b") as second:
        config = ReplayConfig(
            directory=tmp_path / "cassettes",
            upstreams=[
                ReplayUpstream(name="svc-a", url=first.url, kind=UpstreamKind.deterministic),
                ReplayUpstream(name="svc-b", url=second.url, kind=UpstreamKind.deterministic),
            ],
        )
        answers = {}
        for mode in (ReplayMode.record, ReplayMode.replay):
            with proxy_for(config, tmp_path, mode) as proxy:
                proxy.begin(TEST)
                answers[mode] = [
                    send(proxy, method="GET", body=b"", upstream=name).raw
                    for name in ("svc-a", "svc-b")
                ]
                proxy.finish(passed=True)

    assert answers[ReplayMode.record] == answers[ReplayMode.replay] == [b"from-a", b"from-b"]
    assert len(first.seen) == len(second.seen) == 1
    assert len(files(tmp_path / "cassettes")) == 2


def test_a_header_an_upstream_names_is_part_of_its_key_and_another_is_not(
    upstream: FakeUpstream, tmp_path: Path
) -> None:
    named = ReplayUpstream(
        name=UPSTREAM,
        url=upstream.url,
        kind=UpstreamKind.deterministic,
        keyed_headers=["x-model"],
    )
    config = ReplayConfig(directory=tmp_path / "cassettes", upstreams=[named])
    with proxy_for(config, tmp_path, ReplayMode.record) as proxy:
        proxy.begin(TEST)
        send(proxy, headers={"x-model": "m-1"})
        proxy.finish(passed=True)
    with proxy_for(config, tmp_path, ReplayMode.replay) as proxy:
        proxy.begin(TEST)
        send(proxy, headers={"x-model": "m-1", "accept": "text/plain"})
        send(proxy, headers={"x-model": "m-2"})
        proxy.finish(passed=True)

    assert [seen.headers["x-model"] for seen in upstream.seen] == ["m-1", "m-2"]


def test_a_client_that_asks_for_no_compression_gets_none(tmp_path: Path) -> None:
    def compresses_when_asked(seen: Seen) -> Answer:
        if "gzip" in seen.headers.get("accept-encoding", ""):
            return Answer(headers={"Content-Encoding": "gzip"}, chunks=[gzip.compress(b"plain")])
        return Answer(chunks=[b"plain"])

    with FakeUpstream(compresses_when_asked) as upstream:
        config = config_for(upstream.url, tmp_path / "cassettes")
        with proxy_for(config, tmp_path, ReplayMode.record) as proxy:
            proxy.begin(TEST)
            connection = connect(proxy)
            # `request()` would add `Accept-Encoding: identity`; this sends none at all.
            connection.putrequest("GET", "/v1/files", skip_accept_encoding=True)
            connection.endheaders()
            reply = connection.getresponse()
            body = reply.read()
            connection.close()
            proxy.finish(passed=True)

    assert "gzip" not in upstream.seen[0].headers.get("accept-encoding", "")
    assert reply.getheader("content-encoding") is None
    assert body == b"plain"


def test_a_head_answer_the_upstream_marks_chunked_is_headers_alone(tmp_path: Path) -> None:
    chunked = Answer(chunks=[b"one", b"two", b"three"])
    with FakeUpstream(lambda _seen: chunked) as upstream:
        config = config_for(upstream.url, tmp_path / "cassettes")
        with proxy_for(config, tmp_path, ReplayMode.record) as proxy:
            proxy.begin(TEST)
            connection = connect(proxy)
            statuses = []
            for _ in range(2):  # stray bytes would break the second answer on this connection
                connection.request("HEAD", "/v1/files/1")
                reply = connection.getresponse()
                statuses.append((reply.status, reply.read()))
            connection.close()
            proxy.finish(passed=True)

    assert statuses == [(200, b""), (200, b"")]


def test_a_chunked_request_body_reaches_the_upstream_whole(
    upstream: FakeUpstream, tmp_path: Path
) -> None:
    config = config_for(upstream.url, tmp_path / "cassettes")
    with proxy_for(config, tmp_path, ReplayMode.record) as proxy:
        proxy.begin(TEST)
        connection = connect(proxy)
        connection.request(
            "POST",
            "/v1/upload",
            body=iter([b"one-", b"two-", b"three"]),
            headers={"Transfer-Encoding": "chunked"},
            encode_chunked=True,
        )
        reply = connection.getresponse().read()
        connection.close()
        proxy.finish(passed=True)

    assert upstream.seen[0].body == b"one-two-three"
    assert reply == b"echo:one-two-three"


def test_a_head_request_is_answered_with_headers_alone_and_replays(tmp_path: Path) -> None:
    with FakeUpstream(lambda _seen: Answer(chunks=[b"0123456789"])) as upstream:
        config = config_for(upstream.url, tmp_path / "cassettes")
        replies = []
        for mode in (ReplayMode.record, ReplayMode.replay):
            with proxy_for(config, tmp_path, mode) as proxy:
                proxy.begin(TEST)
                replies.append(send(proxy, "/v1/files/1", method="HEAD", body=b""))
                proxy.finish(passed=True)

    assert [(r.status, r.raw, r.headers["content-length"]) for r in replies] == [
        (200, b"", "10")
    ] * 2
    assert len(upstream.seen) == 1


def test_a_secret_in_the_query_string_fails_the_recording(
    upstream: FakeUpstream, tmp_path: Path
) -> None:
    config = config_for(upstream.url, tmp_path / "cassettes")
    with proxy_for(config, tmp_path, ReplayMode.record, secrets=["sk-query-9"]) as proxy:
        proxy.begin(TEST)
        send(proxy, query="key=sk-query-9")
        with pytest.raises(SecretInRecording):
            proxy.finish(passed=True)

    assert files(tmp_path / "cassettes") == []


def test_past_the_directory_size_a_test_s_calls_are_not_promoted_and_it_is_listed(
    tmp_path: Path,
) -> None:
    first, second = "tests/test_a.py::test_one", "tests/test_b.py::test_two"
    with FakeUpstream(lambda _seen: Answer(chunks=[os.urandom(600_000)])) as upstream:
        config = config_for(upstream.url, tmp_path / "cassettes", max_directory_mb=1)
        with proxy_for(config, tmp_path, ReplayMode.record) as proxy:
            for test_id in (first, second):
                proxy.begin(test_id)
                send(proxy)
                proxy.finish(passed=True)

    assert [c.test_id for c in read_cassettes(tmp_path / "cassettes")] == [first]
    assert proxy.over_size == [second]


def test_a_call_still_in_flight_when_the_test_ends_is_not_promoted_and_is_reported(
    tmp_path: Path,
) -> None:
    release = threading.Event()

    def slow(_seen: Seen) -> Answer:
        release.wait(30)
        return Answer()

    with FakeUpstream(slow) as upstream:
        config = config_for(upstream.url, tmp_path / "cassettes")
        with proxy_for(config, tmp_path, ReplayMode.record, settle_seconds=0.1) as proxy:
            proxy.begin(TEST)
            client = threading.Thread(target=send, args=(proxy,))
            client.start()
            wait_for(lambda: bool(upstream.seen), what="the call to reach the upstream")
            proxy.finish(passed=True)
            release.set()
            client.join()

    assert proxy.incomplete == [TEST]
    assert files(tmp_path / "cassettes") == []


def test_the_query_reaches_the_upstream_exactly_as_the_client_sent_it(
    upstream: FakeUpstream, tmp_path: Path
) -> None:
    config = config_for(upstream.url, tmp_path / "cassettes")
    with proxy_for(config, tmp_path, ReplayMode.record) as proxy:
        proxy.begin(TEST)
        send(proxy, query="flag&q=a%20b")
        proxy.finish(passed=True)

    assert upstream.seen[0].path == "/v1/messages?flag&q=a%20b"


def test_an_upstream_that_cannot_be_reached_is_answered_502_and_nothing_is_recorded(
    tmp_path: Path,
) -> None:
    with refused_url() as url:
        config = config_for(url, tmp_path / "cassettes")
        with proxy_for(config, tmp_path, ReplayMode.record) as proxy:
            proxy.begin(TEST)
            reply = send(proxy)
            proxy.finish(passed=True)

    assert reply.status == 502
    assert UPSTREAM in reply.raw.decode()
    assert files(tmp_path / "cassettes") == []


def test_a_failing_test_does_not_wait_for_a_call_still_in_flight(tmp_path: Path) -> None:
    release = threading.Event()

    def slow(_seen: Seen) -> Answer:
        release.wait(30)
        return Answer()

    with FakeUpstream(slow) as upstream:
        config = config_for(upstream.url, tmp_path / "cassettes")
        with proxy_for(config, tmp_path, ReplayMode.record, settle_seconds=30) as proxy:
            proxy.begin(TEST)
            client = threading.Thread(target=send, args=(proxy,))
            client.start()
            wait_for(lambda: bool(upstream.seen), what="the call to reach the upstream")
            started = time.monotonic()
            proxy.finish(passed=False)
            waited = time.monotonic() - started
            release.set()
            client.join()

    assert waited < 5
    assert proxy.incomplete == []
