"""Test support: drive an agent over the policy check's probe commands and say, per command,
whether it reached the client's terminal.

The client allows every permission request and answers a terminal request by recording the
command and returning an empty result: nothing is ever run. The agent gets one prompt per
command, which names the command in an inline code span; a command is judged when its prompt's
turn ends, and it is `reached` when the agent asked the client's terminal for it during that
turn, refused otherwise (by its own configuration, since the client refuses nothing).

The run is bounded: an overall deadline, a progress line on standard error as each command is
judged and a heartbeat on it while none is. The agent is started in a session of its own; on the
deadline, SIGINT or SIGTERM (handlers installed for the run and restored after) its whole process
group is killed and waited for, and every temporary directory of the harness is removed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from agent_build_kit.model import Frozen
from agent_build_kit.runtimes.acp import PROBE_CLASSES

DEADLINE_SECONDS = 600.0
HEARTBEAT_SECONDS = 30.0


class Observation(Frozen):
    """What happened to one probe command."""

    command: str
    label: str
    reached: bool


class HarnessResult(Frozen):
    """The outcome of a drive. `finished` is false when the agent could not be started, the
    deadline passed or a signal ended the run; `error` then says why, and `observations` holds
    the commands judged before it ended. `requested` is every command the client's terminal
    received, in order."""

    finished: bool
    observations: tuple[Observation, ...] = ()
    requested: tuple[str, ...] = ()
    error: str = ""


def drive(
    argv: Sequence[str],
    commands: Sequence[tuple[str, str]] = PROBE_CLASSES,
    *,
    deadline: float = DEADLINE_SECONDS,
    heartbeat: float = HEARTBEAT_SECONDS,
    environment: Mapping[str, str] | None = None,
) -> HarnessResult:
    """Start the agent `argv` names and drive it over `commands` (command, label pairs)."""
    raise NotImplementedError
