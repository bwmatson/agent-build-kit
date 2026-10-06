"""A code host at the HTTP boundary: scripted raw responses, and the requests
that reached it."""

from __future__ import annotations

import json as jsonlib
from pathlib import Path

import httpx

RECORDED = Path(__file__).parent / "recorded"

Reply = httpx.Response | Exception

JSON = {"content-type": "application/json; charset=utf-8"}


def ok(body: object, status: int = 200, **headers: str) -> httpx.Response:
    return httpx.Response(status, content=jsonlib.dumps(body), headers={**JSON, **headers})


def recorded(name: str, **headers: str) -> httpx.Response:
    """A response recorded from the host (names neutralised to fixture owners):
    status, headers and body from recorded/<name>.json. `headers` override the
    recorded ones, for the values that were only true when it was recorded, such
    as an epoch-second reset time."""
    answer = jsonlib.loads((RECORDED / f"{name}.json").read_text())
    return httpx.Response(
        answer["status"],
        content=jsonlib.dumps(answer["body"]),
        headers={**answer["headers"], **headers},
    )


def sign_in_page() -> httpx.Response:
    page = "<!DOCTYPE html><html><head><title>Sign in</title></head><body>Sign in</body></html>"
    return httpx.Response(200, content=page, headers={"content-type": "text/html; charset=utf-8"})


class MockHost(httpx.MockTransport):
    """Answers each request with the next scripted reply (the last one repeats)."""

    def __init__(self, *replies: Reply):
        self.replies = list(replies)
        self.requests: list[httpx.Request] = []
        super().__init__(self._answer)

    def _answer(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        reply = self.replies[min(len(self.requests), len(self.replies)) - 1]
        if isinstance(reply, Exception):
            raise reply
        return reply
