"""What the proxy tests share: a config over one fake upstream, a call through the
proxy that returns the bytes as they came off the wire, and a reader of the files."""

from __future__ import annotations

import gzip
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import httpx

from agent_build_kit.config import ReplayConfig, ReplayUpstream
from agent_build_kit.model import Frozen
from agent_build_kit.replay.models import UpstreamKind
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


def files(directory: Path) -> list[Path]:
    return sorted(directory.rglob("*.json.gz"))


def stored_text(directory: Path) -> str:
    """Everything the cassette files hold, decompressed."""
    return "".join(gzip.decompress(path.read_bytes()).decode() for path in files(directory))
