"""`abk worker`: one piece of work run as its own process."""

from __future__ import annotations

import argparse
from typing import Any

from agent_build_kit import telemetry
from agent_build_kit.cli.pipeline import build_unit, store_for
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import wake


def cmd_worker_build(args: argparse.Namespace, inst: Installation) -> int:
    """Run the unit's graph to its next wait under its branch lock, record the outcome, release
    the lock, touch `runs/wake` and exit 0; non-zero only for a crash before an outcome.

    `build_unit` takes the branch lock, re-reads the unit under it and records how the run
    ended, so a unit another process holds is skipped there. A unit no longer in the store (it
    was joined into another after admission) is a skip too. It reads usage from the snapshot,
    never the endpoint."""
    store = store_for(inst)
    telemetry.init()
    try:
        try:
            unit = store.get(args.unit)
        except KeyError:
            print(f"abk worker build: skipped {args.unit!r}, it is not in the store")
            return 0
        # A comment rework a full resolution lane passed over is the same resolution run here,
        # as `abk tick` starts it in a worker thread.
        build_unit(
            inst,
            unit,
            store=store,
            moved_base_run=unit.comment_rework_owed,
            from_snapshot=True,
        )
    finally:
        wake.touch(inst.state_dir)
        # A worker is a short-lived process: what it recorded would be lost at exit.
        telemetry.shutdown()
    return 0


def cmd_worker_resolve(args: argparse.Namespace, inst: Installation) -> int:
    """Run the pending resolution runs of `args.project` (a project as a person spells it:
    `repo`, or `repo/project`), each carrying its unit through the whole build."""
    raise NotImplementedError


def cmd_worker_verify(args: argparse.Namespace, inst: Installation) -> int:
    """Deploy and run the live tests of `args.change` under the e2e and environment locks, and
    record the result for the dispatcher."""
    raise NotImplementedError


def register(sub: Any) -> None:
    worker = sub.add_parser("worker", help="run one piece of work as its own process")
    kinds = worker.add_subparsers(dest="worker_command", required=True)
    build = kinds.add_parser("build", help="build one unit to its next wait")
    build.add_argument("unit")
    build.set_defaults(func=cmd_worker_build)
