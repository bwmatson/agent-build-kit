"""What the sandbox tests of `abk doctor`, `abk init`, `abk policy check` and `abk status` share:
a registry holding a stand-in backend whose probe a test counts, and the lines that switch the
sandbox on in an `abk.yaml`."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest

from agent_build_kit import sandboxes
from agent_build_kit.sandboxes import Availability, SandboxPolicy
from tests.sandboxes.stand_in import StandInBackend

NAME = "stand-in"


class CountingBackend(StandInBackend):
    """A stand-in that counts how often it was probed."""

    def __init__(self, *, ok: bool = True) -> None:
        super().__init__(NAME, ok=ok)
        self.probes = 0

    def availability(self) -> Availability:
        self.probes += 1
        return super().availability()

    def command(self, policy: SandboxPolicy, argv: Sequence[str]) -> list[str]:
        """Confines nothing, so a command the doctor probe runs through it still runs."""
        super().command(policy, argv)
        if "install-config" in " ".join(argv):
            # A started `abk` is a new process that cannot load a config naming this stand-in.
            return ["true"]
        return list(argv)


def switch_on(config: Path, *, backend: str = NAME) -> None:
    """Append `sandbox.enabled: true` with `backend` to an `abk.yaml`."""
    with config.open("a") as handle:
        handle.write(f"sandbox:\n  enabled: true\n  backend: {backend}\n")


@pytest.fixture
def stand_in() -> Iterator[CountingBackend]:
    """A working stand-in registered under `NAME` for one test."""
    with sandboxes.isolated():
        backend = CountingBackend()
        sandboxes.register(backend)
        yield backend


@pytest.fixture
def broken_stand_in() -> Iterator[CountingBackend]:
    """The same backend, whose probe fails with a cause and a fix."""
    with sandboxes.isolated():
        backend = CountingBackend(ok=False)
        sandboxes.register(backend)
        yield backend
