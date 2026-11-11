"""`abk worker`: one piece of work run as its own process."""

from __future__ import annotations

import argparse
from datetime import datetime
from typing import Any

from agent_build_kit import telemetry
from agent_build_kit.cli.pipeline import (
    build_stack_moves,
    build_turned_move,
    build_unit,
    resolution_procedure,
    store_for,
    verify_and_record,
    verify_once,
)
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import spans, wake
from agent_build_kit.pipeline.admission import ADMISSION_LOCK
from agent_build_kit.pipeline.file_lock import LockTimeout, file_lock
from agent_build_kit.pipeline.occupancy import marker_live, resolve_claimed
from agent_build_kit.pipeline.resolution_lane import (
    clear_deferral,
    clear_worker_record,
    lane_held_by_record,
    owed_units,
    record_deferral,
    write_worker_record,
)
from agent_build_kit.pipeline.units import base_of, project_key, project_tag
from agent_build_kit.pipeline.workspaces import BranchBusy


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

    Each unit gets what the resolution lane gives it (`resolution_procedure`): its attempt budget
    is held, the move its state calls for is made, and the run that remains (a moved-base run
    that never hands the unit back as planned, taking the repo's turn only for the phases that
    write shared git state) is made here, reading usage from the snapshot. A unit a person's tab
    or another run holds, or one no longer owed, is skipped."""
    store = store_for(inst)
    telemetry.init()
    refusals: set[str] = set()

    def refused(unit_id: str, resume_at: datetime | None) -> None:
        # The process ends after its units: the dispatcher asks the guard again next round.
        refusals.add(unit_id)
        if resume_at is not None:
            record_deferral(inst.state_dir, unit_id, resume_at)

    procedure = resolution_procedure(
        inst,
        store,
        moves=build_stack_moves(store, inst, gated=True, refused=refused),
        move=build_turned_move(inst, gated=True, refused=refused),
        refusals=refusals,
        defer=lambda unit_id, resume_at: None,
        build=lambda *args, **kwargs: build_unit(*args, from_snapshot=True, **kwargs),
    )
    try:
        units = store.all()
        owed = owed_units(inst, units)
        for each in units:
            if each.id not in owed or project_tag(each.repo, each.project) != args.project:
                continue
            # Another worker of the project reads the same owed units: the unit is taken under
            # the admission lock, from what is true now, and the record that names this worker
            # as its run is written before the lock is let go.
            with file_lock(inst.locks_dir / ADMISSION_LOCK):
                try:
                    unit = store.get(each.id)
                except KeyError:
                    continue
                now = spans.clock.now()
                current = store.all()
                if unit.id not in owed_units(inst, current):
                    continue  # Run by another worker meanwhile, or no longer owed.
                if unit.id in lane_held_by_record(inst.state_dir):
                    continue  # Another live resolve worker's record names it.
                # A build worker the dispatcher started for the unit (an overflow run) has it.
                if marker_live(unit, now) and not resolve_claimed(unit, now):
                    continue
                # While the run lasts the record names it as the lane's, held by this process.
                record = write_worker_record(
                    inst.state_dir, project_key(unit), unit, base=base_of(unit, current)
                )
                # The run is taken up, so the time a refusal deferred it to is spent. A new
                # refusal in this run records its own.
                clear_deferral(inst.state_dir, unit.id)
                # The record names the run from here, so the claim that started this worker is
                # spent (left live it would count the worker twice until it lapses).
                if resolve_claimed(unit, now):
                    store.set_starting(unit.id, None)
            try:
                rest = procedure(unit)
                if rest is not None:
                    rest()
            except BranchBusy as busy:
                print(f"abk worker resolve: skipped {unit.id} — {busy}")
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
            # With the environment lock held, and the e2e lock `verify_once` takes: a result a
            # worker recorded while this one waited is the result, not deployed again.
            with file_lock(inst.environment_lock):
                verify_and_record(
                    inst,
                    args.change,
                    units,
                    lambda change, units: verify_once(inst, change, units),
                )
        except LockTimeout as busy:
            print(f"abk worker verify: {args.change} not verified now — {busy}")
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
