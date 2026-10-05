"""Which check a failed tier 1 run was (spec: telemetry).

The metrics count a failure by its kind, never by its text, and three kinds
cover what a person acts on: the linter or formatter (`lint`), the type
checker (`types`), the tests (`test`). Which tool means which, and what its
output looks like, is the toolchain profile's to say; this only asks it.
"""

from __future__ import annotations

from agent_build_kit import profiles
from agent_build_kit.config import active

KINDS = ("lint", "types", "test")


def failed_check(output: str, repo: str | None = None) -> str:
    """`lint`, `types` or `test`: what failed in `output`, a tier 1 failure of
    `repo` (its profile reads it; the default profile when `repo` is unnamed)."""
    entry = active().repos.get(repo) if repo else None
    return profiles.get(entry.profile if entry else "python-uv").failure_kind(output)
