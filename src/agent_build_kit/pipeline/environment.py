"""Keeping the pipeline's own environment current, and telling it healthy.

The `environment` section holds argv lists and path lists; nothing here knows a
package manager. The tick hashes the inputs, runs `sync` when they changed, runs
`check`, and heals once when `check` fails. The result is recorded in the state
directory for `abk status`, and units use `problem` to tell a broken environment
from their own failure.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from agent_build_kit.config import EnvironmentConfig, active
from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.command_limit import run_limited

RECORD = "environment.json"


class EnvironmentState(Frozen):
    """What the last tick found: the inputs' hash at the last sync, and the health."""

    hash: str = ""
    healthy: bool = True
    output: str = ""
    since: str = ""


def inputs_hash(environment: EnvironmentConfig, root: Path) -> str:
    """A hash of the contents of every listed input; a missing file counts as missing."""
    digest = hashlib.sha256()
    inputs = environment.inputs
    for name in (*inputs.dependencies, *inputs.lock, *inputs.other):
        path = root / name
        digest.update(name.encode() + b"\0")
        digest.update(path.read_bytes() if path.is_file() else b"<missing>")
        digest.update(b"\0")
    return digest.hexdigest()


def read_state(state_dir: Path) -> EnvironmentState | None:
    try:
        return EnvironmentState.model_validate(json.loads((state_dir / RECORD).read_text()))
    except (OSError, ValueError):
        return None


def _write_state(state_dir: Path, state: EnvironmentState) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / RECORD).write_text(state.model_dump_json())


def _run(command: list[str], root: Path) -> tuple[bool, str]:
    """Whether `command` exits 0 in `root`, and what it printed."""
    limits = active().limits
    try:
        result = run_limited(
            command,
            limit=limits.tier1_command_seconds,
            grace=limits.tier1_abort_grace_seconds,
            cwd=root,
        )
    except OSError as error:
        return False, f"{' '.join(command)} could not run: {error}"
    output = f"{result.stdout or ''}{result.stderr or ''}".strip()
    return result.returncode == 0, output


def problem(root: Path) -> str | None:
    """Why the pipeline's environment is unhealthy now: the output of a failing
    `check`. None when it is healthy, and when no environment is managed."""
    environment = active().environment
    if environment is None:
        return None
    ok, output = _run(environment.check, root)
    return None if ok else output or f"{' '.join(environment.check)} failed"


def ensure(inst: Installation, *, say: Callable[[str], None]) -> bool:
    """Bring the environment up to date before a pass starts work. True when the
    pass may go on: healthy, or none managed. A failure is recorded and printed."""
    environment = inst.config.environment
    if environment is None:
        return True
    previous = read_state(inst.state_dir) or EnvironmentState()
    digest = inputs_hash(environment, inst.root)
    hash_ = previous.hash
    if digest != previous.hash:
        say("environment inputs changed: syncing")
        _, output = _run(environment.sync, inst.root)
        hash_ = digest
        synced = output
    else:
        synced = ""
    ok, output = _run(environment.check, inst.root)
    if not ok:
        say("environment check failed: syncing and checking again")
        _, synced = _run(environment.sync, inst.root)
        hash_ = digest
        ok, output = _run(environment.check, inst.root)
    now = datetime.now(UTC).isoformat()
    if ok:
        _write_state(inst.state_dir, EnvironmentState(hash=hash_, healthy=True, since=now))
        return True
    shown = output or synced or "the check failed with no output"
    since = previous.since if not previous.healthy else now
    _write_state(
        inst.state_dir, EnvironmentState(hash=hash_, healthy=False, output=shown, since=since)
    )
    say(f"environment unhealthy, starting nothing: {shown}")
    return False


__all__ = ["EnvironmentState", "ensure", "inputs_hash", "problem", "read_state"]
