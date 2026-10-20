"""The one normalisation the acceptance declares: two model requests that differ only in the
session id the agent puts in `metadata.user_id` have the same key, and a difference anywhere else
still gives another."""

from __future__ import annotations

import json

from agent_build_kit.replay.models import Request, request_key
from tests.integration import replay_unit_build as build

FIRST = "0d9f7c52-3a41-4e8b-9c1e-6b7a2f5d8e10"
SECOND = "a1b2c3d4-0000-4fff-8aaa-123456789abc"


def request(
    session: str = FIRST,
    *,
    model: str = "model-a",
    system: str = "You are an agent.",
    message: str = "Add the marker.",
    indent: int | None = None,
    compact: bool = True,
) -> Request:
    # As the agent sends it: `JSON.stringify` output has no spaces after `:` or `,`.
    user_id = json.dumps(
        {"device_id": "d", "account_uuid": "", "session_id": session},
        separators=(",", ":") if compact else None,
    )
    body = {
        "model": model,
        "metadata": {"user_id": user_id},
        "system": [{"type": "text", "text": system}],
        "messages": [{"role": "user", "content": message}],
    }
    return Request(
        method="POST",
        path="/v1/messages",
        query="beta=true",
        headers={"content-type": "application/json"},
        body=json.dumps(body, indent=indent).encode(),
    )


def key(asked: Request) -> str:
    return request_key(asked, [build.SESSION_RULE], upstream="model")


def test_two_requests_that_differ_only_in_the_session_id_have_the_same_key() -> None:
    assert key(request(FIRST)) == key(request(SECOND))
    assert key(request(FIRST, indent=2)) == key(request(SECOND))


def test_a_session_id_in_the_spaced_json_shape_is_normalised_too() -> None:
    assert key(request(FIRST, compact=False)) == key(request(SECOND, compact=False))


def test_without_the_rule_the_session_id_alone_changes_the_key() -> None:
    assert request_key(request(FIRST), upstream="model") != request_key(
        request(SECOND), upstream="model"
    )


def test_a_difference_in_any_other_field_gives_another_key() -> None:
    base = key(request())

    assert key(request(model="model-b")) != base
    assert key(request(system="You are another agent.")) != base
    assert key(request(message="Add another marker.")) != base
