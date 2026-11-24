"""The wake file: touching `runs/wake` starts a dispatcher without waiting for the timer."""

from __future__ import annotations

from pathlib import Path

# The wake file's name under the state directory.
WAKE = "wake"


def touch(state_dir: Path) -> None:
    """Touch `<state_dir>/wake`, creating it (and the directory) when absent. Every caller
    reaches the file through this function, as `wake.touch(state_dir)`."""
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / WAKE).touch()
