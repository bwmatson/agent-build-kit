"""The scratch installation a live test builds for one runtime."""

from __future__ import annotations

from collections.abc import Callable

from _pytest.mark.structures import ParameterSet

from agent_build_kit.model import Frozen
from tests.agent_home import TempFactory

RUNTIMES = ("claude_code", "acp")

# One parameter per runtime, each carrying its one `runtime_<name>` tag.
RUNTIME_PARAMS: list[ParameterSet] = []


class RuntimeScratch(Frozen):
    """What a live test needs of a runtime: the `runtimes` entry for `abk.yaml` ("" when none),
    the process environment its `abk` runs with, and the agent's command ([] when none)."""

    runtime: str
    runtimes_yaml: str
    env: dict[str, str]
    command: list[str]


def runtime_scratch(
    runtime: str,
    tmp_path_factory: TempFactory,
    start_check: Callable[[list[str]], None],
) -> RuntimeScratch:
    """The setup for `runtime`; `start_check` is asked, with the agent's command, to confirm the
    agent starts. Fails, never skips, when the runtime's agent command setting is missing."""
    raise NotImplementedError
