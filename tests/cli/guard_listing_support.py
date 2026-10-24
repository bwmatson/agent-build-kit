"""What the tests of the guard listing share: the runtimes under their real names, and the state
a listing gives one guard."""

from __future__ import annotations

from tests.runtimes.selectable import SelectableRuntime

ACTIVE = "active"
SKIPPED = "skipped (confined)"
KEPT = "kept (meaning)"


def named(name: str) -> SelectableRuntime:
    """A selectable runtime that takes a built-in runtime's name, so the guard table, which is
    keyed by runtime name, lists it as that runtime."""
    return SelectableRuntime(name)


def state_of(lines: list[str], guard: str) -> str | None:
    """The state on the line naming `guard`; None when no line names it."""
    for line in lines:
        if guard in line:
            return next((s for s in (ACTIVE, SKIPPED, KEPT) if s in line), "")
    return None
