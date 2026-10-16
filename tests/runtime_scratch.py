"""The scratch installation a live test builds for one runtime."""

from __future__ import annotations

import os
import shlex
from collections.abc import Callable

import pytest
from _pytest.mark.structures import ParameterSet
from pydantic import Field

from agent_build_kit import claude_account
from agent_build_kit.model import Frozen
from tests.agent_home import TempFactory, agent_home

RUNTIMES = ("claude_code", "acp")
AGENT_COMMAND = "ABK_ACCEPTANCE_ACP_COMMAND"

# One parameter per runtime, each carrying its one `runtime_<name>` tag.
RUNTIME_PARAMS: list[ParameterSet] = [
    pytest.param(name, marks=getattr(pytest.mark, f"runtime_{name}")) for name in RUNTIMES
]


class RuntimeScratch(Frozen):
    """What a live test needs of a runtime: the `runtimes` entry for `abk.yaml` ("" when none),
    the process environment its `abk` runs with, and the agent's command ([] when none)."""

    runtime: str
    runtimes_yaml: str
    env: dict[str, str] = Field(repr=False)
    command: list[str]


def runtime_scratch(
    runtime: str,
    tmp_path_factory: TempFactory,
    start_check: Callable[[list[str]], None],
) -> RuntimeScratch:
    """The setup for `runtime`; `start_check` is asked, with the agent's command, to confirm the
    agent starts. Fails, never skips, when the runtime's agent command setting is missing."""
    env = dict(agent_home(tmp_path_factory).env)
    if runtime != "acp":
        env.update({n: os.environ[n] for n in claude_account.NAMES if n in os.environ})
        return RuntimeScratch(runtime=runtime, runtimes_yaml="", env=env, command=[])
    line = os.environ.get(AGENT_COMMAND, "")
    if not line:
        pytest.fail(f"{AGENT_COMMAND} names no agent: this run needs a real one on the host")
    command = shlex.split(line)
    start_check(command)
    return RuntimeScratch(
        runtime=runtime,
        runtimes_yaml=f"runtimes:\n  acp:\n    command: {command}\n",
        env={**env, "ABK_RUNTIME": "acp"},
        command=command,
    )
