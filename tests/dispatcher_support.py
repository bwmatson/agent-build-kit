"""What the dispatcher tests share: a fake spawner standing in for `pipeline.spawn`, and a
workspace for the dispatcher's limits.

The dispatcher reaches the spawner as `spawn.spawn(...)` through its module, so a test replaces
that attribute (and `user_manager_available`); no worker process is started."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit.cli import build_parser
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import spawn
from agent_build_kit.pipeline.spawn import Worker
from tests.tick_pass import workspace


class FakeSpawner:
    """Records each `(kind, unit)` the dispatcher starts and starts nothing; a unit in `refuses`
    raises `OSError` as a spawner that cannot start a process does."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.refuses: set[str] = set()

    def __call__(self, inst: Installation, kind: str, unit: str, **kwargs: object) -> Worker:
        self.calls.append((kind, unit))
        if unit in self.refuses:
            raise OSError("no process")
        return Worker(id=str(len(self.calls)), how="process")

    @property
    def units(self) -> list[str]:
        return [unit for _kind, unit in self.calls]


def install_spawner(monkeypatch: pytest.MonkeyPatch) -> FakeSpawner:
    fake = FakeSpawner()
    monkeypatch.setattr(spawn, "spawn", fake)
    monkeypatch.setattr(spawn, "user_manager_available", lambda run=None: False)
    return fake


def lane_workspace(tmp_path: Path, *, stacks: int, resolutions: int) -> Installation:
    """A workspace with `stacks` build workers and `resolutions` resolution workers at once."""
    return workspace(tmp_path, max_concurrent=stacks, resolutions=resolutions)


def processes_workspace(tmp_path: Path, **kwargs: int) -> Installation:
    return workspace(tmp_path, **kwargs)


def parse_worker_command(*argv: str) -> argparse.Namespace:
    """What `abk worker <argv>` parses to; an assertion failure when it is not a command."""
    try:
        return build_parser().parse_args(["worker", *argv])
    except SystemExit as error:
        raise AssertionError(f"`abk worker {' '.join(argv)}` is not a command") from error
