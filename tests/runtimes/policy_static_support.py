"""What the static policy check's tests share: a scratch agent home holding a
configuration, and the runtime and entry the check is asked about."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from agent_build_kit import runtimes
from agent_build_kit.config import RuntimeConfig
from agent_build_kit.runtimes import AgentRuntime
from agent_build_kit.runtimes.acp import PROBE_CLASSES
from agent_build_kit.runtimes.known_agents import KNOWN_AGENTS, RUNTIME_NAME
from agent_build_kit.runtimes.recommended_policy import UNCOVERED, patterns

LABEL = "what the configuration says, in abk's dialect; not observed from the agent"
FIRST = KNOWN_AGENTS[0]
UNCOVERED_LABELS = {u.label for u in UNCOVERED}
AMEND = "amending a commit"


def said(model: BaseModel, name: str) -> Any:
    """One field of a report or a result, by name."""
    return model.model_dump()[name]


def agent_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty home the first known agent resolves to, through its own variable."""
    assert FIRST.apply is not None
    home = tmp_path / "agent-home"
    home.mkdir()
    monkeypatch.setenv(FIRST.apply.home_env, str(home))
    return home


def write_config(home: Path, deny: list[str] | str) -> Path:
    """The first known agent's configuration file holding `deny`: a block list of
    double-quoted scalars (JSON strings are valid YAML ones), or `deny` as it is when a string."""
    assert FIRST.apply is not None
    path = home / FIRST.apply.file
    if isinstance(deny, str):
        body = f"  deny: {json.dumps(deny)}\n"
    else:
        body = "  deny:\n" + "".join(f"    - {json.dumps(item)}\n" for item in deny)
        body = body if deny else "  deny: []\n"
    path.write_text(f"approvals:\n{body}")
    return path


def recommended() -> list[str]:
    return patterns()


def protocol_runtime() -> AgentRuntime:
    return runtimes.get(RUNTIME_NAME)


def entry_for(*command: str) -> RuntimeConfig:
    return RuntimeConfig(command=list(command))


def first_agent_entry() -> RuntimeConfig:
    return entry_for(FIRST.program, "acp")


def commands_of(label: str) -> list[str]:
    return [command for command, name in PROBE_CLASSES if name == label]
