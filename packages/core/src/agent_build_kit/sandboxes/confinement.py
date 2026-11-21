"""One run's confinement: the backend that wraps each process of the run, behind one allowlist
proxy, and the environment a confined process gets. Every runtime that starts a process under a
`SandboxPolicy` does it through here, so the decisions are made once."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from agent_build_kit import config, sandboxes
from agent_build_kit.sandboxes.base import (
    Coverage,
    SandboxBackend,
    SandboxPolicy,
    SandboxUnavailable,
)
from agent_build_kit.sandboxes.policy import proxy_environment
from agent_build_kit.sandboxes.proxy import Proxy
from agent_build_kit.settings import credential_variables

logger = logging.getLogger(__name__)

# The credential a confined process keeps: it may read a pull request with `gh`.
KEPT_CREDENTIALS = ("gh_token",)


class SandboxRefused(RuntimeError):
    """The sandbox is not what the repo requires, so the process is not started, or it stopped a
    step that ran (a review whose `git` was refused a read); the message says why."""


def scrubbed_environment(base: dict[str, str] | None = None) -> dict[str, str]:
    """`base` (default: this process's environment) without abk's own credentials."""
    kept = dict(os.environ if base is None else base)
    for name in credential_variables(keep=KEPT_CREDENTIALS):
        kept.pop(name, None)
    return kept


class Confinement:
    """The backend and proxy of one run. `wrap` puts the backend's command before an argv;
    `environment` is what a wrapped process needs besides its own (the proxy variables)."""

    def __init__(
        self, backend: SandboxBackend, sandbox: SandboxPolicy, proxy_port: int | None, failure: str
    ) -> None:
        self._backend = backend
        self.sandbox = sandbox
        self.proxy_port = proxy_port
        self._failure = failure

    @property
    def confined(self) -> bool:
        return self.proxy_port is not None

    @property
    def environment(self) -> dict[str, str]:
        return proxy_environment(self.proxy_port) if self.proxy_port is not None else {}

    def wrap(self, argv: list[str]) -> list[str]:
        """`argv` behind the backend's command. Where no backend can confine it: refused, or
        run as it is (and warned about) where the repo's `required` is `none`."""
        if self.proxy_port is None:
            return self._unconfined(argv, self._failure)
        try:
            return self._backend.command(
                self.sandbox.model_copy(update={"proxy_port": self.proxy_port}), argv
            )
        except SandboxUnavailable as error:
            return self._unconfined(argv, str(error))

    def _unconfined(self, argv: list[str], cause: str) -> list[str]:
        if self.sandbox.required is not Coverage.NONE:
            raise SandboxRefused(cause)
        logger.warning("running %s unconfined: %s", argv[0], cause)
        return argv


@contextmanager
def confinement(
    sandbox: SandboxPolicy, on_refused: Callable[[str, int], None] | None = None
) -> Iterator[Confinement]:
    """The confinement of one run under `sandbox`: its allowlist proxy is up for the block, and
    tells `on_refused` each host it refuses."""
    backend, found = sandboxes.probe(config.active().sandbox.backend)
    if not found.ok:
        yield Confinement(backend, sandbox, None, f"{found.cause}: {found.fix}")
        return
    if not found.coverage.reaches(sandbox.required):
        # `required` is the least a step may run with: short of it, the step does not start.
        raise SandboxRefused(
            f"{backend.name} confines {found.coverage.value} of a step, less than the "
            f"{sandbox.required.value} this repo requires: {found.cause} ({found.fix})"
        )
    with Proxy(sandbox.hosts, on_refused=on_refused) as proxy:
        yield Confinement(backend, sandbox, proxy.port, "")
