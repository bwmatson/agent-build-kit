"""One HTTP transport for code hosts: credentials by owner, a timeout on every
call, bounded retry, and the rules for answers that are not the expected one."""

from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable
from typing import Any, Literal

import httpx

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.shell import (
    GH_TOKEN_SOURCE,
    Run,
    credential_source,
    forget_tokens,
)
from agent_build_kit.settings import settings

# Longest single wait between attempts. A host that asks for longer is not waited
# for: the call fails at once with the hint, so a tick never stalls on it.
MAX_DELAY = 60.0
# How much of a page an error quotes.
PAGE_EXCERPT = 200


class TransportError(Exception):
    """Base of every error the transport raises."""


class AuthError(TransportError):
    """401/403, a sign-in page, or no credential for an owner."""


class NotFound(TransportError):
    """A 404, carrying whose credential the call used: a private repo seen
    from the wrong account is reported as missing, not forbidden. `account` is
    the owner the credential was resolved for and `source` where its token came
    from (a GH_TOKEN token may belong to a different account than `account`)."""

    def __init__(self, message: str, *, account: str, source: str):
        super().__init__(message)
        self.account = account
        self.source = source


class RateLimited(TransportError):
    """The host rate-limited the call (a 429, or a 403 carrying GitHub's rate
    limit headers) and kept doing so after the retry bound, or asked for a
    longer wait than the transport will make."""

    def __init__(self, message: str, *, retry_after: float | None):
        super().__init__(message)
        self.retry_after = retry_after


class HostError(TransportError):
    """The host kept failing after the retry bound, or answered 5xx.
    `retry_after` is the host's own hint, when it gave one."""

    def __init__(self, message: str, *, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


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
_locks: dict[tuple[str, str], threading.Lock] = {}
_cache_lock = threading.Lock()


def credential_for(forge: str, owner: str, *, run: Run | None = None) -> Credentials:
    """The credential `owner`'s repos on `forge` are called with.

    The order is `pipeline.shell.credential_source`'s: the explicit setting,
    then the host CLI's logged-in token for that owner, read once and cached.
    Nothing global is switched, so units for different owners can run
    concurrently, and each owner's lookup waits only for its own.
    """
    key = (forge, owner)
    with _cache_lock:
        cached = _cache.get(key)
        lock = _locks.setdefault(key, threading.Lock())
    if cached is not None:
        return cached
    with lock:
        cached = _cache.get(key)
        if cached is None:
            cached = _resolve(forge, owner, run)
            with _cache_lock:
                _cache[key] = cached
        return cached


def clear_credentials() -> None:
    """Forget every cached credential (after a re-login, and between tests)."""
    with _cache_lock:
        _cache.clear()
    forget_tokens()


def _resolve(forge: str, owner: str, run: Run | None) -> Credentials:
    if forge != "github":
        raise AuthError(f"no credential source for a {forge} repo of {owner}")
    found = credential_source(owner, run=run)
    if found is None:
        raise AuthError(
            f"no credential for {owner}: tried {GH_TOKEN_SOURCE} (unset) and "
            f"`gh auth token --user {owner}` (no token); set {GH_TOKEN_SOURCE} or "
            f"run `gh auth login` as {owner}"
        )
    token, source = found
    return Credentials(scheme="Bearer", token=token, source=source, owner=owner)


def _seconds(value: str | None) -> float | None:
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


def _rate_limit_hint(headers: httpx.Headers) -> float | None:
    """Seconds the host asks us to wait: Retry-After, else the time to
    x-ratelimit-reset (an epoch second)."""
    hint = _seconds(headers.get("retry-after"))
    if hint is None:
        reset = _seconds(headers.get("x-ratelimit-reset"))
        hint = max(reset - time.time(), 0.0) if reset is not None else None
    return hint


def _is_rate_limit(reply: httpx.Response) -> bool:
    """429, or GitHub's 403: the primary limit says `x-ratelimit-remaining: 0`,
    the secondary one sends `retry-after`. A plain 403 is a refusal."""
    if reply.status_code == 429:
        return True
    return reply.status_code == 403 and (
        "retry-after" in reply.headers or reply.headers.get("x-ratelimit-remaining") == "0"
    )


class Transport:
    """Calls to one code host as one account. Use as a context manager, or
    `close()` it, to release the connection pool."""

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

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Transport:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

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
                if _is_rate_limit(reply):
                    hint = _rate_limit_hint(reply.headers)
                    failure = RateLimited(f"{method} {path}: rate limited", retry_after=hint)
                elif reply.status_code >= 500:
                    hint = _seconds(reply.headers.get("retry-after"))
                    failure = HostError(
                        f"{method} {path}: host answered {reply.status_code}", retry_after=hint
                    )
                else:
                    return self._answer(method, path, reply, expect)
            # A rate-limited call was refused before it did anything, so
            # repeating it is safe.
            safe = idempotent or isinstance(failure, RateLimited)
            if not safe or attempt >= self.retries or (hint or 0.0) > MAX_DELAY:
                raise failure
            backoff = min(0.5 * 2**attempt * random.uniform(0.5, 1.5), MAX_DELAY)
            self._sleep(max(backoff, hint or 0.0))
            attempt += 1

    def _identity(self) -> str:
        """Whose credential a call used: the owner it was resolved for and where
        the token came from, since the token's own account may differ."""
        return f"with the credential for {self.credentials.owner} from {self.credentials.source}"

    def _answer(
        self, method: str, path: str, reply: httpx.Response, expect: Literal["json", "text"]
    ) -> Response:
        status = reply.status_code
        who = self._identity()
        if status in (401, 403):
            raise AuthError(f"{method} {path}: {status} {who}: {reply.text[:PAGE_EXCERPT]}")
        if status == 404:
            raise NotFound(
                f"{method} {path}: not found {who}",
                account=self.credentials.owner,
                source=self.credentials.source,
            )
        if status >= 400:
            raise TransportError(f"{method} {path}: {status} {who}: {reply.text[:PAGE_EXCERPT]}")
        headers = dict(reply.headers)
        if expect == "text" or not reply.content:
            return Response(status=status, headers=headers, text=reply.text)
        kind = reply.headers.get("content-type", "no content type")
        if "json" not in kind:
            # A sign-in page with a 200 is an authentication failure that looks
            # like success; it must not come back as an empty result.
            raise AuthError(
                f"{method} {path}: expected JSON {who}, got {kind}: {reply.text[:PAGE_EXCERPT]}"
            )
        try:
            data = reply.json()
        except ValueError as error:
            raise HostError(
                f"{method} {path}: unreadable JSON {who}: {reply.text[:PAGE_EXCERPT]}"
            ) from error
        return Response(status=status, headers=headers, data=data, text=reply.text)
