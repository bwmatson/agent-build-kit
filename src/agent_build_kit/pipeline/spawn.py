"""Starting a worker as its own process: a transient systemd user unit, or a detached process."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from typing import Any, Literal

from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen

Run = Callable[..., subprocess.CompletedProcess]


class Worker(Frozen):
    """A started worker: the systemd unit name (`how == "systemd"`) or the pid (`"process"`)."""

    id: str
    how: Literal["systemd", "process"]


def user_manager_available(run: Run | None = None) -> bool:
    """Whether the systemd user manager answers `systemctl --user is-system-running`."""
    raise NotImplementedError


def spawn(
    inst: Installation,
    kind: str,
    unit: str,
    *,
    user_manager: bool,
    run: Run | None = None,
    popen: Callable[..., Any] | None = None,
) -> Worker:
    """Start `abk worker <kind> <unit>`: through `run` as `systemd-run --user --collect` when
    `user_manager`, else through `popen` as a detached process in its own session."""
    raise NotImplementedError
