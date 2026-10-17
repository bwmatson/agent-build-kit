"""Gate evaluation over a temporary state directory: an installation whose `acp` split carries
a gate, readings built to order, and the held set as the e2e-test selection reads it."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.e2e_holds import Hold, Holds, repo_holds
from agent_build_kit.pipeline.gate_holds import GateAction, evaluate_gates
from tests.parked_split_support import installation
from tests.provider_summaries import END, summary

# Ten days into October 2026: the threshold is the pause percent, 70.
NOW = datetime(2026, 10, 11, 0, 0, tzinfo=UTC)
LATER = NOW + timedelta(minutes=20)
END_OF_MONTH = END

PROVIDER_GATE: dict[str, Any] = {"provider": {"name": "modal", "budget_usd": 200}}
COMMAND_GATE: dict[str, Any] = {"command": ["probe", "--quota"]}


def gated(tmp_path: Path, gate: dict[str, Any] | None = None, **overrides: Any) -> Installation:
    """The `acp` split gated on `gate` (the provider by default); `claude_code` has none."""
    return installation(
        tmp_path, acp=None, gate=PROVIDER_GATE if gate is None else gate, **overrides
    )


def spent(percent: int) -> Callable[[], object]:
    """The library's summary at `percent` of a 200 USD budget."""
    return lambda: summary(metered_cost=Decimal(percent * 2))


def unreadable() -> object:
    raise RuntimeError("no login configured")


def command_exiting(code: int, stdout: str = "") -> Callable[..., subprocess.CompletedProcess]:
    """A stand-in for `subprocess.run` that answers every command with `code` and `stdout`."""

    def run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(argv, code, stdout, "")

    return run


def command_missing(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
    raise FileNotFoundError(argv[0])


def evaluate(inst: Installation, *, now: datetime = NOW, **kwargs: Any) -> list[GateAction]:
    return evaluate_gates(inst, now=now, **kwargs)


def holds(inst: Installation, *, now: datetime = NOW) -> Holds:
    """What the e2e-test selection of the `app` repo reads."""
    return repo_holds(inst.config, inst.repo("app"), inst.state_dir, now=now)


def held(inst: Installation, split: str = "acp", *, now: datetime = NOW) -> Hold | None:
    return holds(inst, now=now).held.get(split)
