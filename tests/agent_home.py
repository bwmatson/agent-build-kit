"""A scratch home for the agent an acceptance test starts, and the check that its sessions are kept.

Some agents refuse to open their production session store below a pytest process, so a real agent
started by an acceptance test keeps no sessions and a later step cannot resume one. `agent_home`
gives such an agent a home of its own: a fresh directory (mode 0700) holding symbolic links to the
few files the workspace lists from the person's real home, never the state database. The names come
from three variables the workspace sets in `verify.env`:

- `ABK_ACCEPTANCE_AGENT_HOME_VAR`: the variable the agent reads for its home (unset: no change)
- `ABK_ACCEPTANCE_AGENT_HOME`: the person's real home for the agent (`~` is expanded)
- `ABK_ACCEPTANCE_AGENT_HOME_FILES`: comma-separated file names to link, no separators

Hazards: the agent can rewrite a linked credential through its link (the real file is updated); the
scratch homes live under pytest's temporary directory and go with its retention; the directory holds
links to secrets, so it is 0700 and only names are logged, never contents; a file the agent needs
and the list omits shows up as the agent failing to start, and the fix is to list it.

Fallback, for an agent whose home cannot be relocated: leave the home variable unset and set the
agent's own guard-bypass variable in `verify.env`. The tests' sessions then land in the person's
real session store, with a working directory under the test temporary directory, never removed.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Protocol

import pytest
from pydantic import Field

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.usage_ledger import LEDGER_NAME, read_ledger
from agent_build_kit.runtimes.acp import AcpRuntime

LOG = logging.getLogger(__name__)

HOME_VAR = "ABK_ACCEPTANCE_AGENT_HOME_VAR"
REAL_HOME = "ABK_ACCEPTANCE_AGENT_HOME"
HOME_FILES = "ABK_ACCEPTANCE_AGENT_HOME_FILES"


class TempFactory(Protocol):
    """What `agent_home` asks of pytest's `tmp_path_factory`."""

    def mktemp(self, basename: str, numbered: bool = True) -> Path: ...


class SessionResumer(Protocol):
    """What `assert_session_listed` asks of the runtime."""

    def can_resume_session(self, session_id: str, cwd: Path) -> bool: ...


class AgentHome(Frozen):
    """The scratch home: its `path` (None when not configured), the names `linked` into it and the
    `env` entry that points the agent at it."""

    path: Path | None
    linked: tuple[str, ...]
    env: dict[str, str] = Field(repr=False)

    def apply(self, patch: pytest.MonkeyPatch) -> None:
        """Set `env` in this process, for an agent the test process starts itself or asks (the
        precondition's own spawn), as the child processes get it through their `env=`."""
        for name, value in self.env.items():
            patch.setenv(name, value)


def _required(name: str) -> str:
    value = os.environ.get(name)
    assert value, f"{name} must be set when {HOME_VAR} is set"
    return value


def _refuse_name(name: str, real_home: Path) -> None:
    assert name and "/" not in name and os.sep not in name and name not in (".", ".."), (
        f"{HOME_FILES}: {name!r} is not a plain file name"
    )
    looks_like_store = "state" in name and name.endswith(
        (".db", ".db-wal", ".db-shm", "-wal", "-shm")
    )
    assert not looks_like_store, f"{HOME_FILES}: {name!r} looks like the agent's state database"
    source = real_home / name
    assert source.exists(), f"{name} is listed in {HOME_FILES} but is missing from {real_home}"
    assert not source.is_dir(), f"{HOME_FILES}: {name!r} is a directory; only files are linked"


def agent_home(tmp_path_factory: TempFactory) -> AgentHome:
    """Build the scratch home, or an empty `AgentHome` when the home variable is unset."""
    variable = os.environ.get(HOME_VAR)
    if not variable:
        return AgentHome(path=None, linked=(), env={})
    real_home = Path(_required(REAL_HOME)).expanduser()
    names = tuple(n.strip() for n in _required(HOME_FILES).split(",") if n.strip())
    for name in names:
        _refuse_name(name, real_home)
    scratch = Path(tmp_path_factory.mktemp("agent-home"))
    scratch.chmod(0o700)
    real, fresh = real_home.resolve(), scratch.resolve()
    assert fresh != real and not fresh.is_relative_to(real), (
        f"the scratch home {scratch} is, or is inside, the real home {real_home}"
    )
    for name in names:
        target = (real_home / name).resolve()
        assert not target.is_relative_to(fresh), f"{name} would link inside the scratch home"
        (scratch / name).symlink_to(target)
    LOG.info("agent home %s: linked %s from %s", scratch, ", ".join(names), real_home)
    return AgentHome(path=scratch, linked=names, env={variable: str(scratch)})


def assert_session_listed(runtime: SessionResumer, session_id: str, cwd: Path) -> None:
    """Fail, naming the likely cause, unless the agent lists `session_id` for `cwd`."""
    assert runtime.can_resume_session(session_id, cwd), (
        f"the agent does not list session {session_id} for {cwd} after its first step: it "
        "probably has no session store, because its test guard refuses its production store "
        f"below a pytest process. Check that {HOME_VAR}, {REAL_HOME} and {HOME_FILES} are set "
        "in `verify.env`."
    )


def assert_unit_session_listed(state: Path, unit_id: str, command: list[str], cwd: Path) -> None:
    """`assert_session_listed` for the session of the unit's first agent step, read from the
    usage ledger under `state`, asked of the agent `command` for the step's `cwd`."""
    records = [r for r in read_ledger(state / LEDGER_NAME) if r.unit == unit_id and r.session_id]
    assert records, f"the ledger under {state} holds no agent session for {unit_id}"
    first = records[0].session_id
    assert first is not None
    runtime = AcpRuntime()
    runtime.agent_command = tuple(command)
    assert_session_listed(runtime, first, cwd)
