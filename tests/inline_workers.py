"""Workers that run in the test's process: what stands in for the spawner when a test drives
`abk tick` and wants the builds it dispatches to run.

A worker is a thread running the unit's build, as the process `abk worker build` would, and
`tick_and_wait` returns once every worker the tick started has ended."""

from __future__ import annotations

import argparse
import contextvars
import threading

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import spawn
from agent_build_kit.pipeline.spawn import Worker


class InlineWorkers:
    """Stands in for `spawn.spawn`: each call starts a thread that builds the unit."""

    def __init__(self) -> None:
        self.threads: list[threading.Thread] = []
        self.started = 0
        self.died: list[BaseException] = []

    def __call__(self, inst: Installation, kind: str, unit: str, **kwargs: object) -> Worker:
        self.started += 1
        work = contextvars.copy_context()

        def run() -> None:
            store = cli.store_for(inst)
            try:
                work.run(
                    cli.build_unit,
                    inst,
                    store.get(unit),
                    store=store,
                    moved_base_run=store.get(unit).comment_rework_owed,
                )
            except Exception:  # noqa: BLE001 — a worker's error is its unit's, recorded by it
                pass
            except BaseException as error:  # noqa: BLE001 — a worker killed is seen by the tick
                self.died.append(error)
            finally:
                # The worker has the branch's lock, or is done: the claim has nothing to hold.
                if store.get(unit).starting is not None:
                    store.set_starting(unit, None)

        thread = threading.Thread(target=run, name=f"worker-{unit}")
        self.threads.append(thread)
        thread.start()
        return Worker(id=str(self.started), how="process")

    def join(self) -> None:
        """Wait for every worker; one that died with an error raises it here, as a process
        killed mid-run is seen by whoever waits for it."""
        while self.threads:
            self.threads.pop().join()
        if self.died:
            raise self.died.pop(0)


WORKERS = InlineWorkers()


def install(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the spawner with the in-process workers."""
    monkeypatch.setattr(spawn, "spawn", WORKERS)
    monkeypatch.setattr(spawn, "user_manager_available", lambda run=None: False)


def tick_and_wait(inst: Installation, args: argparse.Namespace) -> int:
    """One `abk tick`, then the workers it started run to their ends."""
    code = cli.cmd_tick(args, inst)
    WORKERS.join()
    return code
