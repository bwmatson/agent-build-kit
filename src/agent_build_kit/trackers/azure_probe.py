"""What the Azure DevOps doctor probe says about a project, one line for each check."""

from __future__ import annotations

from agent_build_kit.model import Frozen


class ProbeLine(Frozen):
    """One check: whether it passed, and what it found, naming the level, type or state at
    fault. Never a credential."""

    ok: bool
    text: str
