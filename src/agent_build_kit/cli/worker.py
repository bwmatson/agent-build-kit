"""`abk worker`: one piece of work run as its own process."""

from __future__ import annotations

import argparse
from typing import Any

from agent_build_kit import telemetry
from agent_build_kit.cli.pipeline import build_unit
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.snapshots import WAKE
from agent_build_kit.pipeline.unit_store import UnitStore


def cmd_worker_build(args: argparse.Namespace, inst: Installation) -> int:
    """Run the unit's graph to its next wait under its branch lock, record the outcome, release
    the lock, touch `runs/wake` and exit 0; non-zero only for a crash before an outcome.

    `build_unit` takes the branch lock, re-reads the unit under it and records how the run
    ended, so a unit another process holds is skipped there. A unit no longer in the store (it
    was joined into another after admission) is a skip too. It reads usage from the snapshot,
    never the endpoint."""
    store = UnitStore(inst.state_dir / "units.json")
    telemetry.init()
    try:
        try:
            unit = store.get(args.unit)
        except KeyError:
            print(f"abk worker build: skipped {args.unit!r}, it is not in the store")
            return 0
        build_unit(inst, unit, store=store, from_snapshot=True)
    finally:
        (inst.state_dir / WAKE).touch()
        # A worker is a short-lived process: what it recorded would be lost at exit.
        telemetry.shutdown()
    return 0


def register(sub: Any) -> None:
    worker = sub.add_parser("worker", help="run one piece of work as its own process")
    kinds = worker.add_subparsers(dest="worker_command", required=True)
    build = kinds.add_parser("build", help="build one unit to its next wait")
    build.add_argument("unit")
    build.set_defaults(func=cmd_worker_build)
