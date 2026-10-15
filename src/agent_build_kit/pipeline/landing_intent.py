"""The record of a landing in progress.

Written before the forge merges, removed once the merge is recorded.
"""

import json
from pathlib import Path

from agent_build_kit.pipeline.file_lock import atomic_write_text

# In the state directory beside the other state files.
LANDING = "landing.json"


class IntentNotWritten(Exception):
    """The intent could not be recorded, so no merge may be asked for."""


def _key(repo: str, pr: int) -> str:
    return f"{repo}#{pr}"


def _read(path: Path) -> dict[str, dict[str, str]]:
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _write(path: Path, intents: dict[str, dict[str, str]]) -> None:
    atomic_write_text(path, json.dumps(intents, indent=2, sort_keys=True))


def record_intent(path: Path, *, repo: str, pr: int, unit: str) -> None:
    intents = _read(path)
    intents[_key(repo, pr)] = {"repo": repo, "unit": unit}
    try:
        _write(path, intents)
    except OSError as error:
        raise IntentNotWritten(f"landing intent for {repo} #{pr} not written: {error}") from error


def clear_intent(path: Path, *, repo: str, pr: int) -> None:
    intents = _read(path)
    if intents.pop(_key(repo, pr), None) is not None:
        _write(path, intents)


def has_intent(path: Path, *, repo: str, pr: int) -> bool:
    return _key(repo, pr) in _read(path)
