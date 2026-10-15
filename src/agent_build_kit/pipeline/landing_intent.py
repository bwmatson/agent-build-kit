"""The record of a landing in progress.

Written before the forge merges, removed once the merge is recorded.
"""

from pathlib import Path

# In the state directory beside the other state files.
LANDING = "landing.json"


class IntentNotWritten(Exception):
    """The intent could not be recorded, so no merge may be asked for."""


def record_intent(path: Path, *, repo: str, pr: int, unit: str) -> None:
    raise NotImplementedError


def clear_intent(path: Path, *, repo: str, pr: int) -> None:
    raise NotImplementedError


def has_intent(path: Path, *, repo: str, pr: int) -> bool:
    raise NotImplementedError
