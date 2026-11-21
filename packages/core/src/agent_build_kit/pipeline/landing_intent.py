"""The record of a landing in progress.

Written before the forge merges, removed once the merge is recorded.
"""

import json
from contextlib import AbstractContextManager
from pathlib import Path

from agent_build_kit.pipeline.file_lock import atomic_write_text, file_lock

# In the state directory beside the other state files.
LANDING = "landing.json"

Records = dict[str, dict[str, str | int]]


class IntentNotWritten(Exception):
    """The intent could not be recorded, so no merge may be asked for."""


def _key(repo: str, pr: int) -> str:
    return f"{repo}:{pr}"


def _read(path: Path) -> Records | None:
    """The records: empty when there is no file, None when it is there and unreadable."""
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return raw if isinstance(raw, dict) else None


def _lock(path: Path) -> AbstractContextManager[None]:
    return file_lock(path.with_name(f"{path.name}.lock"))


def record_intent(path: Path, *, repo: str, pr: int, unit: str) -> None:
    try:
        with _lock(path):
            intents = _read(path)
            if intents is None:
                # Writing over it would drop the other landings' records.
                raise IntentNotWritten(f"{path.name} is there but cannot be read")
            intents[_key(repo, pr)] = {"repo": repo, "pr": pr, "unit": unit}
            atomic_write_text(path, json.dumps(intents, indent=2, sort_keys=True))
    except OSError as error:
        raise IntentNotWritten(f"landing intent for {repo} #{pr} not written: {error}") from error


def clear_intent(path: Path, *, repo: str, pr: int) -> None:
    with _lock(path):
        intents = _read(path)
        if intents is not None and intents.pop(_key(repo, pr), None) is not None:
            atomic_write_text(path, json.dumps(intents, indent=2, sort_keys=True))


def has_intent(path: Path, *, repo: str, pr: int) -> bool:
    return _key(repo, pr) in (_read(path) or {})
