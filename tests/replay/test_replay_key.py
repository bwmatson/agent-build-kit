"""The key a cassette is found by: what the upstream sees, and never a credential."""

import json

import pytest

from agent_build_kit.replay.models import Request, request_key

BODY = json.dumps({"model": "m-1", "messages": [{"role": "user", "content": "hi"}]}).encode()
HEADERS = {"content-type": "application/json", "accept": "application/json"}


def asked(**changes) -> Request:
    base = Request(method="POST", path="/v1/messages", query="a=1&b=2", headers=HEADERS, body=BODY)
    return base.model_copy(update=changes)


def test_the_same_request_gives_the_same_key() -> None:
    assert request_key(asked()) == request_key(asked())


def test_the_order_of_the_query_and_of_the_json_keys_does_not_matter() -> None:
    reordered = json.dumps(
        {"messages": [{"content": "hi", "role": "user"}], "model": "m-1"}, indent=2
    ).encode()
    assert request_key(asked(query="b=2&a=1", body=reordered)) == request_key(asked())


@pytest.mark.parametrize(
    "changes",
    [
        {"body": BODY.replace(b"hi", b"ho")},
        {"query": "a=1&b=3"},
        {"path": "/v1/other"},
        {"method": "GET"},
        {"headers": {**HEADERS, "accept": "text/event-stream"}},
        {"headers": {**HEADERS, "content-type": "text/plain"}},
    ],
    ids=["body", "query", "path", "method", "accept", "content-type"],
)
def test_a_difference_in_what_the_upstream_sees_gives_another_key(changes: dict) -> None:
    assert request_key(asked(**changes)) != request_key(asked())


@pytest.mark.parametrize("credential", ["authorization", "x-api-key", "cookie"])
def test_a_credential_header_is_not_part_of_the_key(credential: str) -> None:
    first = asked(headers={**HEADERS, credential: "secret-one"})
    second = asked(headers={**HEADERS, credential: "secret-two"})
    assert request_key(first) == request_key(second) == request_key(asked())
