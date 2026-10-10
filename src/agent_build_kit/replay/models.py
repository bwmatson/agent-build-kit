"""What a recording is made of: the mode, the kind of upstream, the request the key
is taken from, and the cassette stored for one call."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from enum import StrEnum

from agent_build_kit.model import Frozen


class ReplayMode(StrEnum):
    off = "off"
    record = "record"
    replay = "replay"
    live = "live"


class UpstreamKind(StrEnum):
    deterministic = "deterministic"
    llm = "llm"


class Outcome(StrEnum):
    hit = "hit"
    missed = "missed"
    unused = "unused"
    aged_out = "aged_out"


class Rule(Frozen):
    """A declared normalisation: what matches in a request, and what stands in for it."""

    pattern: str
    placeholder: str


class Request(Frozen):
    method: str
    path: str
    # The query string as sent, without the `?`.
    query: str = ""
    headers: Mapping[str, str] = {}
    body: bytes = b""


class RequestSummary(Frozen):
    method: str
    path: str
    query: str
    body_size: int
    body_hash: str


class StoredResponse(Frozen):
    status: int
    headers: dict[str, str]
    # The body as received, in the order received; one chunk when not streamed.
    chunks: list[bytes]


class Cassette(Frozen):
    key: str
    upstream: str
    kind: UpstreamKind
    recorded_at: datetime
    test_id: str
    call_index: int
    rules: list[Rule] = []
    request: RequestSummary
    response: StoredResponse
    needs_review: bool = False


def request_key(request: Request, rules: Sequence[Rule] = ()) -> str:
    """The hash of what the upstream sees: method, path, sorted query, the allowlisted
    headers and the body after `rules`. Credentials are never part of it."""
    raise NotImplementedError
