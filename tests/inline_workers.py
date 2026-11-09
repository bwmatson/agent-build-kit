"""Workers that run in the test's process: what stands in for the spawner when a test drives
`abk tick` and wants the work it dispatches to run.

A worker is the command the real spawner would start as a process: `abk worker build <unit>`,
`resolve <project>` or `verify <change>`, with the namespace the `worker` parser builds for it.
It runs to its end inside the spawn, in the tick's own context, so what it records nests under
the tick's span and is exported with the tick's telemetry; its own `telemetry.shutdown()` is
left out, since a process ending is what flushes there and the tick flushes here. A worker that
raised is raised again when the tick returns, as a process that crashed is seen by whoever waits
for it."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import Any

import pytest

from agent_build_kit import telemetry
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.cli import worker as worker_cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import spawn
from agent_build_kit.pipeline.spawn import Worker

Command = Callable[[argparse.Namespace, Installation], int]

# What each kind of worker runs, with the name of the argument `worker`'s parser gives it.
COMMANDS: dict[str, tuple[Command, str]] = {
    "build": (worker_cli.cmd_worker_build, "unit"),
    "resolve": (worker_cli.cmd_worker_resolve, "project"),
    "verify": (worker_cli.cmd_worker_verify, "change"),
}


REAL_SHUTDOWN = telemetry.shutdown


class _SharedTelemetry:
    """The telemetry module as a worker sees it in a test: the tick's providers stay up."""

    def __getattr__(self, name: str) -> Any:
        return getattr(telemetry, name)

    @staticmethod
    def shutdown() -> None:
        # A test that spies on the shutdown sees the worker's call; the real one is left out.
        if telemetry.shutdown is not REAL_SHUTDOWN:
            telemetry.shutdown()


class InlineWorkers:
    """Stands in for `spawn.spawn`: each call runs the worker's command to its end."""

    def __init__(self) -> None:
        self.started = 0
        self.ran: list[tuple[str, str]] = []
        self.died: list[BaseException] = []

    def reset(self) -> None:
        """Nothing a test before this one ran is left to be raised."""
        self.started = 0
        self.ran.clear()
        self.died.clear()

    def __call__(self, inst: Installation, kind: str, target: str, **kwargs: object) -> Worker:
        if kind not in COMMANDS:
            raise ValueError(f"no worker of kind {kind!r}")
        command, argument = COMMANDS[kind]
        self.started += 1
        self.ran.append((kind, target))
        try:
            command(argparse.Namespace(**{argument: target}), inst)
        except BaseException as error:  # noqa: BLE001 — seen by whoever joins
            self.died.append(error)
        return Worker(id=str(self.started), how="process")

    def join(self, *, raising: bool = True) -> None:
        """The first worker that raised is raised here."""
        if raising and self.died:
            raise self.died.pop(0)


WORKERS = InlineWorkers()


def install(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the spawner with the in-process workers, and `cmd_tick` with a call that raises
    what a worker raised once the tick has returned."""
    monkeypatch.setattr(spawn, "spawn", WORKERS)
    monkeypatch.setattr(spawn, "user_manager_available", lambda run=None: False)
    monkeypatch.setattr(worker_cli, "telemetry", _SharedTelemetry())
    dispatch = cli.cmd_tick

    def tick_and_wait(args: argparse.Namespace, inst: Installation) -> int:
        try:
            return dispatch(args, inst)
        finally:
            WORKERS.join()

    monkeypatch.setattr(cli, "cmd_tick", tick_and_wait)
