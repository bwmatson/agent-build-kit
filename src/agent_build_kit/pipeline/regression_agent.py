"""The regression agent: works out why a test fails and since when, judges whether the test or
the implementation is wrong, and writes the one change that fixes it (spec: regression-agent).
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.flakes import Flake
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.runtimes import AgentRuntime


class FixKind(StrEnum):
    """What kind of failure the change is written for."""

    FLAKY = "flaky"
    PRE_EXISTING = "pre-existing"
    REGRESSION = "regression"


class FixOutcome(Frozen):
    """The change the agent wrote, and whether a person has to look at it before the unit's wait
    on it can end: `held` with the reason it could not be accepted."""

    change: str
    held: bool = False
    reason: str = ""


def write_fix_change(
    inst: Installation,
    failure: Flake,
    unit: StoredUnit,
    *,
    kind: FixKind,
    base: str,
    base_output: str = "",
    runtime: AgentRuntime,
    cwd: Path,
) -> FixOutcome:
    """Run the agent for `failure` in `cwd`, a checkout of the unit's `base`, and check the
    change it wrote."""
    raise NotImplementedError
