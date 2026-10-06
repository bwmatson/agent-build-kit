"""One HTTP transport for code hosts: credentials by owner, a timeout on every
call, bounded retry, and the rules for answers that are not the expected one."""

from __future__ import annotations

import random
import subprocess
import threading
import time
from collections.abc import Callable
from typing import Any, Literal

import httpx

from agent_build_kit.model import Frozen
from agent_build_kit.settings import settings

Run = Callable[..., subprocess.CompletedProcess]

# Longest single wait between attempts, unless the host's own Retry-After asks for more.
MAX_DELAY = 60.0
# How much of a page an error quotes.
PAGE_EXCERPT = 200


class TransportError(Exception):
    """Base of every error the transport raises."""


class AuthError(TransportError):
    """401/403, a sign-in page, or no credential for an owner."""


class NotFound(TransportError):
    """A 404, carrying the account the call was made as: a private repo seen
    from the wrong account is reported as missing, not forbidden."""

    def __init__(self, message: str, *, account: str):
        super().__init__(message)
        self.account = account


class RateLimited(TransportError):
    """The host kept answering 429 after the retry bound."""

    def __init__(self, message: str, *, retry_after: float | None):
        super().__init__(message)
        self.retry_after = retry_after


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


_cache: dict[tuple[str, str], Credentials] = {}
_cache_lock = threading.Lock()


def credential_for(forge: str, owner: str, *, run: Run = subprocess.run) -> Credentials:
    """The credential `owner`'s repos on `forge` are called with.

    The explicit setting wins, then the host CLI's logged-in token for that
    owner, read once and cached. Nothing global is switched, so units for
    different owners can run concurrently.
    """
    with _cache_lock:
        cached = _cache.get((forge, owner))
        if cached is None:
            cached = _cache[(forge, owner)] = _resolve(forge, owner, run)
        return cached


def clear_credentials() -> None:
    """Forget every cached credential (after a re-login, and between tests)."""
    with _cache_lock:
        _cache.clear()


def _resolve(forge: str, owner: str, run: Run) -> Credentials:
    if forge != "github":
        raise AuthError(f"no credential source for a {forge} repo of {owner}")
    if settings.gh_token:
        return Credentials(scheme="Bearer", token=settings.gh_token, source="GH_TOKEN", owner=owner)
    result = run(
        ["gh", "auth", "token", "--user", owner], capture_output=True, text=True, check=False
    )
    token = "" if result.returncode else (result.stdout or "").strip()
    if not token:
        raise AuthError(
            f"no credential for {owner}: tried GH_TOKEN (unset) and "
            f"`gh auth token --user {owner}` (no token); set GH_TOKEN or "
            f"run `gh auth login` as {owner}"
        )
    return Credentials(
        scheme="Bearer", token=token, source=f"gh auth token --user {owner}", owner=owner
    )


def _seconds(value: str | None) -> float | None:
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


class Transport:
    """Calls to one code host as one account."""

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
        self.credentials = credentials
        self.retries = settings.forge_retries if retries is None else retries
        self._sleep = sleep
        self._client = httpx.Client(
            base_url=base_url,
            transport=transport,
            timeout=settings.forge_timeout_seconds if timeout is None else timeout,
            headers={
                "Authorization": f"{credentials.scheme} {credentials.token}",
                "Accept": "application/json",
            },
        )

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
        """One call. `idempotent` defaults from the method: a create-style POST
        is never repeated blindly, because a timeout may have created it."""
        method = method.upper()
        if idempotent is None:
            idempotent = method in ("GET", "HEAD", "OPTIONS", "PUT", "DELETE")
        attempt = 0
        while True:
            hint: float | None = None
            try:
                reply = self._client.request(method, path, json=json, params=params)
            except httpx.TransportError as error:
                failure: TransportError = HostError(f"{method} {path}: {error!r}")
            else:
                hint = _seconds(reply.headers.get("retry-after"))
                if reply.status_code == 429:
                    failure = RateLimited(f"{method} {path}: rate limited", retry_after=hint)
                elif reply.status_code >= 500:
                    failure = HostError(f"{method} {path}: host answered {reply.status_code}")
                else:
                    return self._answer(method, path, reply, expect)
            # A 429 was refused before it did anything, so repeating it is safe.
            safe = idempotent or isinstance(failure, RateLimited)
            if not safe or attempt >= self.retries:
                raise failure
            backoff = min(0.5 * 2**attempt * random.uniform(0.5, 1.5), MAX_DELAY)
            self._sleep(max(backoff, hint or 0.0))
            attempt += 1

    def _answer(
        self, method: str, path: str, reply: httpx.Response, expect: Literal["json", "text"]
    ) -> Response:
        status = reply.status_code
        who = self.credentials.owner
        if status in (401, 403):
            raise AuthError(f"{method} {path}: {status} as {who}: {reply.text[:PAGE_EXCERPT]}")
        if status == 404:
            raise NotFound(f"{method} {path}: not found as account {who}", account=who)
        if status >= 400:
            raise TransportError(f"{method} {path}: {status} as {who}: {reply.text[:PAGE_EXCERPT]}")
        headers = dict(reply.headers)
        if expect == "text" or not reply.content:
            return Response(status=status, headers=headers, text=reply.text)
        kind = reply.headers.get("content-type", "no content type")
        if "json" not in kind:
            # A sign-in page with a 200 is an authentication failure that looks
            # like success; it must not come back as an empty result.
            raise AuthError(
                f"{method} {path}: expected JSON as {who}, got {kind}: {reply.text[:PAGE_EXCERPT]}"
            )
        return Response(status=status, headers=headers, data=reply.json(), text=reply.text)
