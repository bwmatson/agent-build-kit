"""What a recording is made of: the mode, the kind of upstream, the request the key
is taken from, and the cassette stored for one call."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from enum import StrEnum
from urllib.parse import parse_qsl

from pydantic import ConfigDict

from agent_build_kit.model import Frozen

# The request headers that change an answer; every other header, credentials included, is
# neither keyed nor stored.
KEYED_HEADERS = frozenset({"content-type", "accept", "anthropic-version", "anthropic-beta"})
# The response headers a cassette keeps.
STORED_HEADERS = frozenset({"content-type", "content-encoding"})


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
    model_config = ConfigDict(ser_json_bytes="base64", val_json_bytes="base64")

    status: int
    headers: dict[str, str]
    # The body as received, in the order received; one chunk when not streamed.
    chunks: list[bytes]


class Cassette(Frozen):
    model_config = ConfigDict(ser_json_bytes="base64", val_json_bytes="base64")

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


def _rewritten(text: str, rules: Sequence[Rule]) -> str:
    for rule in rules:
        text = re.sub(rule.pattern, rule.placeholder, text)
    return text


def applied_rules(request: Request, rules: Sequence[Rule]) -> list[Rule]:
    """The rules whose pattern matches somewhere in `request`."""
    text = "\n".join((request.path, request.query, request.body.decode(errors="replace")))
    return [rule for rule in rules if re.search(rule.pattern, text)]


def request_key(request: Request, rules: Sequence[Rule] = ()) -> str:
    """The hash of what the upstream sees: method, path, sorted query, the allowlisted
    headers and the body after `rules`. Credentials are never part of it."""
    text = _rewritten(request.body.decode(errors="replace"), rules)
    try:
        body: object = json.dumps(json.loads(text), sort_keys=True, separators=(",", ":"))
    except ValueError:
        body = text
    headers = {
        name: value.strip()
        for name, value in sorted((k.lower(), v) for k, v in request.headers.items())
        if name in KEYED_HEADERS
    }
    query = sorted(parse_qsl(_rewritten(request.query, rules), keep_blank_values=True))
    canonical = json.dumps(
        [request.method.upper(), _rewritten(request.path, rules), query, headers, body]
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def summarise(request: Request) -> RequestSummary:
    return RequestSummary(
        method=request.method,
        path=request.path,
        query=request.query,
        body_size=len(request.body),
        body_hash=hashlib.sha256(request.body).hexdigest(),
    )
