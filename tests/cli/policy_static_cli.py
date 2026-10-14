"""What the CLI tests of the static policy check share: an installation whose runtime is the
protocol one with a given command, and a snapshot of what a command may not change."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent_build_kit.runtimes.known_agents import RUNTIME_NAME
from tests.cli.policy_step_fakes import configured
from tests.runtimes.policy_static_support import FIRST, protocol_runtime

UNKNOWN_PROGRAM = "some-unknown-agent"


def agent_command(program: str = FIRST.program) -> list[str]:
    return [program, "acp"]


def planning_for(
    tmp_path: Path,
    app: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: list[str],
    *,
    policy_fix: list[str] | None = None,
) -> Path:
    """A laid-out planning repo whose runtime is the real protocol one, started by `command`."""
    return configured(
        tmp_path, app, monkeypatch, protocol_runtime(), command=command, policy_fix=policy_fix
    )


def abk_yaml(tmp_path: Path, command: list[str]) -> Path:
    """The smallest abk.yaml selecting the protocol runtime with `command`."""
    planning = tmp_path / "planning"
    planning.mkdir(exist_ok=True)
    path = planning / "abk.yaml"
    path.write_text(
        yaml.safe_dump({"runtime": RUNTIME_NAME, "runtimes": {RUNTIME_NAME: {"command": command}}})
    )
    return path


def snapshot(*roots: Path) -> dict[str, bytes]:
    """Every file under `roots` with its bytes."""
    return {str(p): p.read_bytes() for r in roots for p in sorted(r.rglob("*")) if p.is_file()}
