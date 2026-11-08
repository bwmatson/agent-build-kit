"""`abk worker`: one piece of work run as its own process."""

from __future__ import annotations

import argparse
from typing import Any

from agent_build_kit import telemetry
from agent_build_kit.cli.pipeline import (
    StackBusy,
    _demote_failed_verify,
    _merged_ids,
    build_unit,
    store_for,
    verify_one,
)
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import spans, wake
from agent_build_kit.pipeline.file_lock import LockTimeout, file_lock
from agent_build_kit.pipeline.occupancy import marker_live, resolve_claimed
from agent_build_kit.pipeline.resolution_lane import (
    clear_worker_record,
    owed_units,
    write_worker_record,
)
from agent_build_kit.pipeline.units import base_of, project_key, project_tag
from agent_build_kit.pipeline.verify import SplitHeld, Verification, VerifyRecord


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
    `repo`, or `repo/project`), each carrying its unit through the whole build.

    A run is the unit's own build flagged as a moved-base run: it never hands the unit back as
    planned, and `build_unit` takes the repo's turn only for the phases that write shared git
    state. A unit another process holds, or one no longer owed, is skipped there."""
    store = store_for(inst)
    telemetry.init()
    try:
        units = store.all()
        owed = owed_units(inst, units)
        now = spans.clock.now()
        for each in units:
            if each.id not in owed or project_tag(each.repo, each.project) != args.project:
                continue
            try:
                unit = store.get(each.id)
            except KeyError:
                continue
            # A build worker the dispatcher started for the unit (an overflow run) has it.
            if marker_live(unit, now) and not resolve_claimed(unit, now):
                continue
            # While the run lasts the record names it as the lane's, held by this process.
            record = write_worker_record(
                inst.state_dir,
                project_key(unit),
                unit,
                base=base_of(unit, units),
            )
            try:
                build_unit(inst, unit, store=store, moved_base_run=True, from_snapshot=True)
            finally:
                clear_worker_record(record)
    finally:
        wake.touch(inst.state_dir)
        telemetry.shutdown()
    return 0


def cmd_worker_verify(args: argparse.Namespace, inst: Installation) -> int:
    """Deploy and run the live tests of `args.change` under the e2e and environment locks, and
    record the result for the dispatcher, which archives the change on its next round.

    A live stack in use or a split still held is no result: nothing is recorded and the
    dispatcher starts a worker again."""
    store = store_for(inst)
    telemetry.init()
    try:
        units = store.all()
        try:
            with file_lock(inst.environment_lock):
                outcome = verify_one(inst, args.change, units)
        except (StackBusy, SplitHeld, LockTimeout) as busy:
            print(f"abk worker verify: {args.change} not verified now — {busy}")
            return 0
        except Exception as error:  # noqa: BLE001 — recorded, never silently skipped
            outcome = Verification(
                change=args.change,
                passed=False,
                detail=f"{type(error).__name__}: {error}",
                units=_merged_ids(args.change, units),
            )
        VerifyRecord(inst.state_dir / "verified.json").put(outcome)
        if outcome.passed:
            print(f"verified {args.change}: {', '.join(outcome.deployed) or 'nothing to deploy'}")
        else:
            print(f"verification of {args.change} failed:\n{outcome.detail}")
            _demote_failed_verify(inst, args.change, units)
    finally:
        wake.touch(inst.state_dir)
        telemetry.shutdown()
    return 0


def register(sub: Any) -> None:
    worker = sub.add_parser("worker", help="run one piece of work as its own process")
    kinds = worker.add_subparsers(dest="worker_command", required=True)
    build = kinds.add_parser("build", help="build one unit to its next wait")
    build.add_argument("unit")
    build.set_defaults(func=cmd_worker_build)
    resolve = kinds.add_parser("resolve", help="run a project's pending resolution runs")
    resolve.add_argument("project")
    resolve.set_defaults(func=cmd_worker_resolve)
    verify = kinds.add_parser("verify", help="deploy a merged change and run its live tests")
    verify.add_argument("change")
    verify.set_defaults(func=cmd_worker_verify)
