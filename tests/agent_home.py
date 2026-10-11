"""A scratch home for the agent an acceptance test starts, and the check that its sessions are kept.

Stubs: the behaviour is specified by `tests/test_agent_home.py`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_build_kit.model import Frozen

HOME_VAR = "ABK_ACCEPTANCE_AGENT_HOME_VAR"
REAL_HOME = "ABK_ACCEPTANCE_AGENT_HOME"
HOME_FILES = "ABK_ACCEPTANCE_AGENT_HOME_FILES"


class AgentHome(Frozen):
    """The scratch home: its `path` (None when not configured), the names `linked` into it and the
    `env` entry that points the agent at it."""

    path: Path | None
    linked: tuple[str, ...]
    env: dict[str, str]


def agent_home(tmp_path_factory: Any) -> AgentHome:
    raise NotImplementedError


def assert_session_listed(runtime: Any, session_id: str, cwd: Path) -> None:
    raise NotImplementedError
