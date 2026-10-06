"""One HTTP transport for code hosts: credentials by owner, a timeout on every
call, bounded retry, and the rules for answers that are not the expected one."""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from typing import Any, Literal

import httpx

from agent_build_kit.model import Frozen

Run = Callable[..., subprocess.CompletedProcess]


class TransportError(Exception):
    """Base of every error the transport raises."""


class AuthError(TransportError):
    """401/403, a sign-in page, or no credential for an owner."""


class NotFound(TransportError):
    account: str


class RateLimited(TransportError):
    retry_after: float | None


class HostError(TransportError):
    """The host kept failing after the retry bound, or answered 5xx."""


class Credentials(Frozen):
    scheme: str
    token: str
    source: str
    owner: str


class Response(Frozen):
    status: int
    headers: dict[str, str]
    data: Any = None
    text: str = ""


def credential_for(forge: str, owner: str, *, run: Run = subprocess.run) -> Credentials:
    raise NotImplementedError


def clear_credentials() -> None:
    raise NotImplementedError


class Transport:
    def __init__(
        self,
        base_url: str,
        credentials: Credentials,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float | None = None,
        retries: int | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        raise NotImplementedError

    def request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, str] | None = None,
        idempotent: bool | None = None,
        expect: Literal["json", "text"] = "json",
    ) -> Response:
        raise NotImplementedError
