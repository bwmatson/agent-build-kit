"""Which of the kit's guards a runtime has active, skipped because the step is confined, or kept
because they are about meaning: the one table `abk policy check` and `abk status` list from."""

from __future__ import annotations

from agent_build_kit.installation import Installation
from agent_build_kit.runtimes.base import AgentRuntime


def guard_lines(runtime: AgentRuntime, installation: Installation) -> list[str]:
    """One line per guard of `runtime`: its name and whether it is active, skipped (confined)
    or kept (meaning), given the installation's sandbox setting and the runtime's coverage."""
    raise NotImplementedError
