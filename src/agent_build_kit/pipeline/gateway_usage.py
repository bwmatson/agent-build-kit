"""An agent run's exact usage, from the gateway's own records for a key of its own."""

from __future__ import annotations

import http.client
import json
import time
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable
from contextvars import ContextVar
from typing import Any, Protocol

from agent_build_kit.model import Frozen
from agent_build_kit.settings import settings
from agent_build_kit.usage import Usage

# The environment variable a run's key is handed to the agent in.
KEY_ENV = "ABK_GATEWAY_KEY"

TIMEOUT_SECONDS = 10

# Where the agent call being made sits, `<unit>:<node>:<round>`: set by the step
# that makes the call, read by whatever mints its key.
attribution: ContextVar[str] = ContextVar("gateway_attribution", default="")


class Spend(Frozen):
    """What a run spent, as a usage source read it: absent when it could not."""

    usage: Usage | None = None
    cost_usd: float | None = None


class SpendSource(Protocol):
    """Where a run's usage can be read from besides what the agent reports."""

    def begin(self, place: str) -> tuple[dict[str, str], object]:
        """The environment to start the agent with for the call at `place`, and a handle."""
        ...

    def finish(self, handle: object) -> Spend:
        """What the run spent; always releases whatever `begin` took."""
        ...


class GatewayError(Exception):
    """A gateway call that failed in transport, status or decoding."""


class GatewayUsage:
    """A `SpendSource` over a gateway's key and spend endpoints.

    Every failure is said once and leaves the run as it would have been without
    a gateway: no key, no figures.

    A gateway writes its spend logs in periodic batches and files each row under
    the hash of the key, which it also accepts the raw key for. So `finish`
    asks by the raw key and, while nothing is there yet, asks again every
    `poll_seconds` for up to `settle_seconds` before saying the key logged
    nothing.
    """

    def __init__(
        self,
        url: str,
        master_key: str,
        say: Callable[[str], None],
        *,
        settle_seconds: float = 30.0,
        poll_seconds: float = 1.0,
    ) -> None:
        self.url = url.rstrip("/")
        self.master_key = master_key
        self.say = say
        self.settle_seconds = settle_seconds
        self.poll_seconds = poll_seconds

    def _call(self, method: str, path: str, body: dict | None = None) -> Any:
        request = urllib.request.Request(
            self.url + path,
            data=json.dumps(body).encode() if body is not None else None,
            method=method,
            headers={
                "Authorization": f"Bearer {self.master_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as reply:
                return json.loads(reply.read() or b"null")
        except (OSError, ValueError, http.client.HTTPException) as error:
            raise GatewayError(str(error) or type(error).__name__) from error

    def begin(self, place: str) -> tuple[dict[str, str], object]:
        alias = f"abk:{place}:{uuid.uuid4().hex[:12]}"
        try:
            key = self._call("POST", "/key/generate", {"key_alias": alias})["key"]
        except (GatewayError, KeyError, TypeError) as error:
            self.say(f"gateway: could not mint a key ({error}); usage is not read from it")
            return {}, None
        return {KEY_ENV: key}, key

    def finish(self, handle: object) -> Spend:
        if not isinstance(handle, str):
            return Spend()
        try:
            return self._spend(handle)
        finally:
            try:
                self._call("POST", "/key/delete", {"keys": [handle]})
            except GatewayError as error:
                self.say(f"gateway: could not revoke a run's key ({error})")

    def _rows(self, key: str) -> list[dict]:
        """The rows logged for `key`, waiting for a batched write to land."""
        deadline = time.monotonic() + self.settle_seconds
        while True:
            rows = self._call("GET", "/spend/logs?" + urllib.parse.urlencode({"api_key": key}))
            if rows or time.monotonic() >= deadline:
                return rows or []
            time.sleep(self.poll_seconds)

    def _spend(self, key: str) -> Spend:
        try:
            rows = self._rows(key)
            if not rows:
                # Nothing logged for the key: the agent never spent through it, or
                # the gateway has not written its rows yet or files them under
                # something the lookup does not match. Not evidence of no spend.
                self.say(
                    f"gateway: no spend was logged for a run's key within "
                    f"{self.settle_seconds:g}s; using what the agent said"
                )
                return Spend()
            # An OpenAI-shaped gateway's `prompt_tokens` includes cached input and
            # gives no breakdown here, so `input_tokens` of a gateway record does too.
            usage = Usage(
                input_tokens=sum(int(row.get("prompt_tokens") or 0) for row in rows),
                output_tokens=sum(int(row.get("completion_tokens") or 0) for row in rows),
            )
            return Spend(usage=usage, cost_usd=sum(float(row.get("spend") or 0) for row in rows))
        except (GatewayError, ValueError, AttributeError, TypeError) as error:
            self.say(f"gateway: could not read a run's spend ({error}); using what the agent said")
            return Spend()


def configured_source(say: Callable[[str], None], warned: set[str]) -> SpendSource | None:
    """The gateway source the settings name, or None when they name none.

    `warned` is the caller's: a half-configured setting is said once per set.
    """
    url, master_key = settings.gateway_url, settings.gateway_master_key
    if not url and not master_key:
        return None
    if not url or not master_key:
        missing = "gateway_url" if not url else "gateway_master_key"
        if missing not in warned:
            warned.add(missing)
            say(f"gateway: {missing} is not set, so no gateway key is minted")
        return None
    return GatewayUsage(url, master_key, say, settle_seconds=settings.gateway_settle_seconds)
