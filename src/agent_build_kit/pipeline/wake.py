"""The wake file: touching `runs/wake` starts a dispatcher without waiting for the timer."""

from __future__ import annotations

from pathlib import Path


def touch(state_dir: Path) -> None:
    """Touch `<state_dir>/wake`, creating it (and the directory) when absent. Every caller
    reaches the file through this function, as `wake.touch(state_dir)`."""
    raise NotImplementedError
