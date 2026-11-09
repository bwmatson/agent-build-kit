"""Workers that run in the test's process: what stands in for the spawner when a test drives
`abk tick` and wants the work it dispatches to run.

A worker is a thread running the command the real spawner would start as a process:
`abk worker build <unit>`, `resolve <project>` or `verify <change>`, with the namespace the
`worker` parser builds for it. `install` replaces the spawner and makes `cmd_tick` return once
every worker it started has ended; a worker that raised is raised again there, as a process that
crashed is seen by whoever waits for it."""

from __future__ import annotations

import argparse
import contextvars
import threading
from collections.abc import Callable

import pytest

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


class InlineWorkers:
    """Stands in for `spawn.spawn`: each call starts a thread that runs the worker's command."""

    def __init__(self) -> None:
        self.threads: list[threading.Thread] = []
        self.started = 0
        self.ran: list[tuple[str, str]] = []
        self.died: list[BaseException] = []

    def reset(self) -> None:
        """Nothing a test before this one started is left to run or to raise."""
        self.join(raising=False)
        self.started = 0
        self.ran.clear()
        self.died.clear()

    def __call__(self, inst: Installation, kind: str, target: str, **kwargs: object) -> Worker:
        if kind not in COMMANDS:
            raise ValueError(f"no worker of kind {kind!r}")
        command, argument = COMMANDS[kind]
        self.started += 1
        self.ran.append((kind, target))
        work = contextvars.copy_context()
        args = argparse.Namespace(**{argument: target})

        def run() -> None:
            try:
                work.run(command, args, inst)
            except BaseException as error:  # noqa: BLE001 — seen by whoever joins
                self.died.append(error)

        thread = threading.Thread(target=run, name=f"worker-{kind}-{target}")
        self.threads.append(thread)
        thread.start()
        return Worker(id=str(self.started), how="process")

    def join(self, *, raising: bool = True) -> None:
        """Wait for every worker; the first that raised is raised here."""
        while self.threads:
            self.threads.pop().join()
        if raising and self.died:
            raise self.died.pop(0)


WORKERS = InlineWorkers()


def install(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the spawner with the in-process workers, and `cmd_tick` with a call that returns
    once the workers it started have ended."""
    monkeypatch.setattr(spawn, "spawn", WORKERS)
    monkeypatch.setattr(spawn, "user_manager_available", lambda run=None: False)
    dispatch = cli.cmd_tick

    def tick_and_wait(args: argparse.Namespace, inst: Installation) -> int:
        try:
            return dispatch(args, inst)
        finally:
            WORKERS.join()

    monkeypatch.setattr(cli, "cmd_tick", tick_and_wait)
