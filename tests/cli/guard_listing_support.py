"""What the tests of the guard listing share: how to read one guard's state out of the lines."""

from __future__ import annotations

from agent_build_kit.runtimes.guards import ACTIVE, KEPT, SKIPPED


def state_of(lines: list[str], guard: str) -> str | None:
    """The state on the line naming `guard`; None when no line names it, empty when the line
    carries none of the three."""
    for line in lines:
        if guard in line:
            return next((s for s in (ACTIVE, SKIPPED, KEPT) if s in line), "")
    return None
