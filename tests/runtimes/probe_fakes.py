"""The host a probe asks, faked: which programs are on the path, and what their
`--help` prints. Handed to `detect(which, run)` as it is to `abk doctor`'s checks."""

from __future__ import annotations

import subprocess
import sys
from typing import Any

import pytest

from agent_build_kit import runtimes
from agent_build_kit.runtimes import known_agents
from agent_build_kit.runtimes.known_agents import KnownAgent, StartVariant

# Neutral stand-ins for the known-agent table: one spelling, one that varies by
# version and is chosen from the help, and one more to show the probe goes on.
PLAIN = KnownAgent(
    name="svc-a",
    program="svc-a",
    variants=(StartVariant(argv=("svc-a", "acp")),),
    needs="a running gateway",
    verified="documented only",
    source="https://example.test/svc-a",
)
VARYING = KnownAgent(
    name="svc-b",
    program="svc-b",
    variants=(
        StartVariant(argv=("svc-b", "serve"), marker="svc-b serve"),
        StartVariant(argv=("svc-b", "--legacy-serve"), marker="--legacy-serve"),
    ),
    verified="documented only",
    source="https://example.test/svc-b",
)
OTHER = KnownAgent(
    name="svc-c",
    program="svc-c",
    variants=(StartVariant(argv=("svc-c", "run"), marker="run"),),
    verified="documented only",
    source="https://example.test/svc-c",
)
HELP_TIMEOUT = 5


class Host:
    def __init__(
        self,
        programs: tuple[str, ...] = (),
        *,
        helps: dict[str, str] | None = None,
        hangs: tuple[str, ...] = (),
    ) -> None:
        self.programs = programs
        self.helps = helps or {}
        self.hangs = hangs
        self.runs: list[tuple[list[str], dict[str, Any]]] = []

    def which(self, program: str) -> str | None:
        return f"/bin/{program}" if program in self.programs else None

    def run(self, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        self.runs.append((list(argv), kwargs))
        if argv[0] in self.hangs:
            raise subprocess.TimeoutExpired(argv, kwargs.get("timeout", 0))
        return subprocess.CompletedProcess(argv, 0, stdout=self.helps.get(argv[0], ""), stderr="")


def table(monkeypatch: pytest.MonkeyPatch, *agents: KnownAgent) -> None:
    monkeypatch.setattr(known_agents, "KNOWN_AGENTS", agents)


def without_library(monkeypatch: pytest.MonkeyPatch) -> None:
    """The `acp` extra not installed, as the import system reports it: the library
    cannot be imported, so the protocol runtime is not registered."""
    monkeypatch.setattr(runtimes, "_REGISTRY", {})
    monkeypatch.setitem(sys.modules, "acp", None)
    monkeypatch.delitem(sys.modules, "agent_build_kit.runtimes.acp", raising=False)
    monkeypatch.delattr(runtimes, "acp", raising=False)
