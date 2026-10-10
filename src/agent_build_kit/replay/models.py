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

# The request headers that change an answer unless an upstream names others; every other
# header, credentials included, is neither keyed nor stored.
DEFAULT_KEYED_HEADERS = ("content-type", "accept")
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
    # For a JSON object body: a digest per top-level field, and per element of a list field
    # (`messages[1]`), so a difference can be named without storing the prompts.
    parts: dict[str, str] = {}


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
    # Why it waits for review; empty when it does not.
    review_reason: str = ""


def _rewritten(text: str, rules: Sequence[Rule]) -> str:
    for rule in rules:
        text = re.sub(rule.pattern, rule.placeholder, text)
    return text


def applied_rules(request: Request, rules: Sequence[Rule]) -> list[Rule]:
    """The rules whose pattern matches somewhere in `request`."""
    text = "\n".join((request.path, request.query, request.body.decode(errors="replace")))
    return [rule for rule in rules if re.search(rule.pattern, text)]


def request_key(
    request: Request,
    rules: Sequence[Rule] = (),
    *,
    upstream: str = "",
    keyed_headers: Sequence[str] = DEFAULT_KEYED_HEADERS,
) -> str:
    """The hash of what the upstream sees: its name, method, path, sorted query, the
    `keyed_headers` and the body after `rules`. Credentials are never part of it."""
    text = _rewritten(request.body.decode(errors="replace"), rules)
    try:
        body: object = json.dumps(json.loads(text), sort_keys=True, separators=(",", ":"))
    except ValueError:
        body = text
    headers = {
        name: value.strip()
        for name, value in sorted((k.lower(), v) for k, v in request.headers.items())
        if name in {header.lower() for header in keyed_headers}
    }
    query = sorted(parse_qsl(_rewritten(request.query, rules), keep_blank_values=True))
    canonical = json.dumps(
        [upstream, request.method.upper(), _rewritten(request.path, rules), query, headers, body]
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:16]


def _parts(body: bytes) -> dict[str, str]:
    try:
        payload = json.loads(body)
    except ValueError:
        return {}
    if not isinstance(payload, dict):
        return {}
    parts: dict[str, str] = {}
    for name, value in payload.items():
        if isinstance(value, list):
            parts.update({f"{name}[{index}]": _digest(item) for index, item in enumerate(value)})
            parts[f"{name}[]"] = str(len(value))
        else:
            parts[name] = _digest(value)
    return parts


def summarise(request: Request) -> RequestSummary:
    return RequestSummary(
        method=request.method,
        path=request.path,
        query=request.query,
        body_size=len(request.body),
        body_hash=hashlib.sha256(request.body).hexdigest(),
        parts=_parts(request.body),
    )


def describe_difference(held: RequestSummary, asked: RequestSummary) -> str:
    """Where `asked` differs from `held`: "path differs", "differs at system, messages[1]"."""
    found = [
        f"{name} differs"
        for name in ("method", "path", "query")
        if getattr(held, name) != getattr(asked, name)
    ]
    if held.body_hash != asked.body_hash:
        if held.parts and asked.parts:
            names = sorted(
                name
                for name in held.parts.keys() | asked.parts.keys()
                if held.parts.get(name) != asked.parts.get(name) and not name.endswith("[]")
            )
        else:
            names = []
        found.append(f"differs at {', '.join(names)}" if names else "body differs")
    return "; ".join(found) or "the key differs (a declared rule or a header)"
