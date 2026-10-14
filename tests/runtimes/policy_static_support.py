"""What the static policy check's tests share: a scratch agent home holding a
configuration, and the runtime and entry the check is asked about."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from agent_build_kit import runtimes
from agent_build_kit.config import RuntimeConfig
from agent_build_kit.runtimes import AgentRuntime
from agent_build_kit.runtimes.acp import PROBE_CLASSES
from agent_build_kit.runtimes.known_agents import KNOWN_AGENTS, RUNTIME_NAME
from agent_build_kit.runtimes.recommended_policy import UNCOVERED

LABEL = "what the configuration says, in abk's dialect; not observed from the agent"
FIRST = KNOWN_AGENTS[0]
UNCOVERED_LABELS = {u.label for u in UNCOVERED}


def agent_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty home the first known agent resolves to, through its own variable."""
    assert FIRST.apply is not None
    home = tmp_path / "agent-home"
    home.mkdir()
    monkeypatch.setenv(FIRST.apply.home_env, str(home))
    return home


def config_file(home: Path) -> Path:
    """Where the first known agent keeps its configuration under `home`."""
    assert FIRST.apply is not None
    return home / FIRST.apply.file


def write_config(home: Path, deny: list[str] | str) -> Path:
    """The first known agent's configuration file holding `deny`: a block list of
    double-quoted scalars (JSON strings are valid YAML ones), or `deny` as it is when a string."""
    path = config_file(home)
    if isinstance(deny, str):
        body = f"  deny: {json.dumps(deny)}\n"
    else:
        body = "  deny:\n" + "".join(f"    - {json.dumps(item)}\n" for item in deny)
        body = body if deny else "  deny: []\n"
    path.write_text(f"approvals:\n{body}")
    return path


def protocol_runtime() -> AgentRuntime:
    return runtimes.get(RUNTIME_NAME)


def entry_for(*command: str) -> RuntimeConfig:
    return RuntimeConfig(command=list(command))


def first_agent_entry() -> RuntimeConfig:
    return entry_for(FIRST.program, "acp")


def commands_of(label: str) -> list[str]:
    return [command for command, name in PROBE_CLASSES if name == label]


def recording_program(directory: Path) -> Path:
    """A program named for the first known agent that records any start in `started.log`
    beside `directory` and exits non-zero."""
    directory.mkdir(exist_ok=True)
    path = directory / FIRST.program
    path.write_text(f"#!/bin/sh\necho started >> {directory.parent / 'started.log'}\nexit 1\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path
