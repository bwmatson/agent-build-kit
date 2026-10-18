"""What the proxy tests share: a config over one fake upstream, a call through the
proxy that returns the bytes as they came off the wire, and a reader of the files."""

from __future__ import annotations

import gzip
import hashlib
import socket
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

# Imported here so pytester's module snapshot cannot swap out httpx's lazily imported httpcore.
import httpcore  # noqa: F401
import httpx
import pytest

from agent_build_kit.config import ReplayConfig, ReplayUpstream
from agent_build_kit.model import Frozen
from agent_build_kit.replay.models import Cassette, RequestSummary, StoredResponse, UpstreamKind
from agent_build_kit.replay.report import ReplayedTest
from agent_build_kit.replay.store import cassette_name
from tests.replay.proxy import ReplayProxy

UPSTREAM = "svc-a"
ENV = "SVC_A_URL"
START = datetime(2030, 1, 1, 9, 0, tzinfo=UTC)


class Reply(Frozen):
    status: int
    headers: dict[str, str]
    # Off the wire: a gzip-encoded body is still compressed.
    raw: bytes


def config_for(
    url: str,
    directory: Path,
    *,
    kind: UpstreamKind = UpstreamKind.deterministic,
    **limits: int,
) -> ReplayConfig:
    upstream = ReplayUpstream(name=UPSTREAM, url=url, kind=kind, env=[ENV])
    return ReplayConfig(upstreams=[upstream], directory=directory, **limits)


def send(
    proxy: ReplayProxy,
    path: str = "/v1/messages",
    *,
    body: bytes = b"{}",
    query: str = "",
    headers: Mapping[str, str] | None = None,
    method: str = "POST",
    upstream: str = UPSTREAM,
) -> Reply:
    url = proxy.addresses[upstream] + path + (f"?{query}" if query else "")
    with httpx.stream(method, url, content=body, headers=dict(headers or {})) as response:
        raw = b"".join(response.iter_raw())
        return Reply(status=response.status_code, headers=dict(response.headers), raw=raw)


@contextmanager
def refused_url() -> Iterator[str]:
    """The base URL of a loopback port that refuses every connection and that nothing else
    can take for as long as the block runs: a closed port may be handed to another test."""
    # Bound and never listening: connections are refused, and the port stays ours.
    with socket.socket() as held:
        held.bind(("127.0.0.1", 0))
        yield f"http://127.0.0.1:{held.getsockname()[1]}"


def files(directory: Path) -> list[Path]:
    return sorted(directory.rglob("*.json.gz"))


def stored_text(directory: Path) -> str:
    """Everything the cassette files hold, decompressed."""
    return "".join(gzip.decompress(path.read_bytes()).decode() for path in files(directory))


def waiting_cassette(
    test_id: str,
    call_index: int = 0,
    *,
    path: str = "/v1/messages",
    needs_review: bool = True,
    reason: str = "no run asked for it",
    kind: UpstreamKind = UpstreamKind.deterministic,
) -> Cassette:
    """A cassette as an earlier recording left it, by default waiting for review."""
    key = hashlib.sha256(f"{test_id}|{call_index}|{path}".encode()).hexdigest()
    return Cassette(
        key=key,
        upstream=UPSTREAM,
        kind=kind,
        recorded_at=START,
        test_id=test_id,
        call_index=call_index,
        request=RequestSummary(
            method="POST",
            path=path,
            query="",
            body_size=2,
            body_hash=hashlib.sha256(b"{}").hexdigest(),
        ),
        response=StoredResponse(status=200, headers={}, chunks=[b"ok"]),
        needs_review=needs_review,
        review_reason=reason if needs_review else "",
    )


def run_session(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    *args: str,
    **modules: str,
) -> pytest.RunResult:
    """An inner pytest session with the replay plugin, in `mode`, over the given modules."""
    monkeypatch.setenv("ABK_REPLAY_MODE", mode)
    pytester.makepyfile(**modules)
    return pytester.runpytest_inprocess(
        "-p", "tests.replay.plugin", "-p", "no:cacheprovider", *args
    )


def replayed_cassettes(
    recorded: Sequence[Cassette], directory: Path, test: ReplayedTest
) -> list[Cassette]:
    """The recorded cassettes a run answered from: those it asked for again, and that were
    young enough to answer. A cassette no call asked for is in `test.unused`, and one that
    matched but was too old is in `test.aged_out`."""
    return [
        c
        for c in recorded
        if cassette_name(directory, c) not in test.unused and c.key not in test.aged_out
    ]
