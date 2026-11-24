"""Which of the kit's guards a runtime has active, skipped because the step is confined, or kept
because they are about meaning: the one table `abk policy check` and `abk status` list from.

A guard that only says where an agent may write stands down when the kernel confines the step and
is the fallback otherwise; a guard about meaning, or about a location the sandbox cannot express,
stays in both modes (`docs/designs/sandbox-design.md`)."""

from __future__ import annotations

from enum import StrEnum

from agent_build_kit import sandboxes
from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.runtimes.base import AgentRuntime
from agent_build_kit.sandboxes import step_confined


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


def confined_repos(runtime: AgentRuntime, installation: Installation) -> dict[str, bool]:
    """Whether a step in each configured repo runs confined: the sandbox is on, a backend works
    on this machine (a machine with none runs every step unconfined) and the runtime reaches
    what the repo requires (the pipeline's own rule, `step_confined`)."""
    config = installation.config
    working = config.sandbox.enabled and sandboxes.probe(config.sandbox.backend)[1].ok
    return {
        name: working and step_confined(repo.sandbox.required, runtime.sandbox_coverage)
        for name, repo in config.repos.items()
    }


def _state(guard: Guard, confined: dict[str, bool]) -> str:
    if guard.kind is Kind.KEPT:
        return KEPT
    skipped = [name for name, on in confined.items() if on]
    active = [name for name, on in confined.items() if not on]
    if not active:
        return SKIPPED
    if not skipped:
        return ACTIVE
    return f"{SKIPPED} for {', '.join(skipped)}; {ACTIVE} for {', '.join(active)}"


def guard_lines(runtime: AgentRuntime, installation: Installation) -> list[str]:
    """One line per guard of `runtime`: its name and whether it is active, skipped (confined)
    or kept (meaning). The states describe unit steps, which each repo's `sandbox.required`
    decides; a track run is never confined and keeps every location guard."""
    confined = confined_repos(runtime, installation) or {"": False}
    return [
        f"guard {guard.name}: {_state(guard, confined)}"
        for guard in GUARDS
        if runtime.name in guard.runtimes
    ]
