"""Which of the kit's guards a runtime has active, skipped because the step is confined, or kept
because they are about meaning: the one table `abk policy check` and `abk status` list from.

A guard that only says where an agent may write stands down when the kernel confines the step and
is the fallback otherwise; a guard about meaning, or about a location the sandbox cannot express,
stays in both modes (`docs/sandbox-design.md`)."""

from __future__ import annotations

from enum import StrEnum

from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.runtimes.base import AgentRuntime
from agent_build_kit.sandboxes import Coverage


class Kind(StrEnum):
    LOCATION = "location"
    KEPT = "kept"


class Guard(Frozen):
    name: str
    kind: Kind
    runtimes: tuple[str, ...]


CLAUDE_CODE = "claude_code"
ACP = "acp"

# Every guard the listing shows, in the order it shows them.
GUARDS: tuple[Guard, ...] = (
    Guard(name="worktree check", kind=Kind.LOCATION, runtimes=(CLAUDE_CODE,)),
    Guard(name="specs fence", kind=Kind.LOCATION, runtimes=(CLAUDE_CODE,)),
    Guard(name="config text fence", kind=Kind.LOCATION, runtimes=(CLAUDE_CODE,)),
    Guard(name="command-text fence", kind=Kind.LOCATION, runtimes=(ACP,)),
    Guard(name="merge rules", kind=Kind.KEPT, runtimes=(CLAUDE_CODE, ACP)),
    Guard(name="planning paths", kind=Kind.KEPT, runtimes=(CLAUDE_CODE, ACP)),
    Guard(name="redirect rule", kind=Kind.KEPT, runtimes=(CLAUDE_CODE, ACP)),
    Guard(name="client file checks", kind=Kind.KEPT, runtimes=(ACP,)),
)

ACTIVE = "active"
SKIPPED = "skipped (confined)"
KEPT = "kept (meaning)"


def is_confined(runtime: AgentRuntime, installation: Installation) -> bool:
    """Whether a step of `runtime` runs confined under this installation's settings."""
    return installation.config.sandbox.enabled and runtime.sandbox_coverage is not Coverage.NONE


def guard_lines(runtime: AgentRuntime, installation: Installation) -> list[str]:
    """One line per guard of `runtime`: its name and whether it is active, skipped (confined)
    or kept (meaning), given the installation's sandbox setting and the runtime's coverage."""
    confined = is_confined(runtime, installation)
    lines = []
    for guard in GUARDS:
        if runtime.name not in guard.runtimes:
            continue
        if guard.kind is Kind.KEPT:
            state = KEPT
        else:
            state = SKIPPED if confined else ACTIVE
        lines.append(f"guard {guard.name}: {state}")
    return lines
