"""`abk carry`: carry a unit that landed off the default branch onto it, on demand
(spec: landed-off-default-units-are-carried)."""

from __future__ import annotations

import argparse
import sys

from agent_build_kit import run_support
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.carry import carried_commit, carry_branch, is_carrying
from agent_build_kit.pipeline.events import (
    AGENT_UNAVAILABLE,
    build_claim,
    carry_unit,
    record_landed,
)
from agent_build_kit.pipeline.landing_check import merged_on_default
from agent_build_kit.pipeline.restack import RestackConflict
from agent_build_kit.pipeline.unit_store import Cause, StoredUnit
from agent_build_kit.pipeline.units import HELD, MERGED, trunk_of
from agent_build_kit.pipeline.workspaces import BranchBusy


def _say(text: str, *, error: bool = False) -> None:
    print(text, file=sys.stderr if error else sys.stdout)


def _may_record_landing(unit: StoredUnit) -> bool:
    """Whether a commit on the default branch can be recorded as the unit's: its work is in
    another branch (held for it), already carried, or recorded merged."""
    held_off = unit.state == HELD and unit.cause is Cause.LANDED_OFF_DEFAULT
    return held_off or unit.state == MERGED or is_carrying(unit)


def _landed_as(args: argparse.Namespace, inst: Installation, unit: StoredUnit) -> int:
    store = run_support.store_for(inst)
    repo, trunk = inst.checkouts[unit.repo], trunk_of(unit.repo)
    if not _may_record_landing(unit):
        _say(
            f"{unit.id} is {unit.state}; --landed-as is for a unit held for landing, "
            "in review on a carry, or merged"
        )
        return 1
    if not merged_on_default(repo, args.landed_as, trunk):
        _say(f"{unit.id}: {args.landed_as} is not on the default branch ({trunk})")
        return 1
    if args.dry_run:
        _say(f"would record {args.landed_as} as the merge commit of {unit.id}")
        return 0
    try:
        with build_claim(inst.locks_dir)(unit):
            current = store.get(unit.id)
            if not _may_record_landing(current):
                _say(f"{unit.id} is now {current.state}; run abk carry again")
                return 1
            if current.state == MERGED:
                store.set_merge_record(unit.id, args.landed_as, None)
            else:
                record_landed(
                    store,
                    current,
                    args.landed_as,
                    lambda each: run_support.merge_record_of(inst, each),
                    run_support.thread_resumer(inst, store),
                )
    except BranchBusy as error:
        _say(f"{unit.id}: not recorded — {error}", error=True)
        return 1
    _say(f"{unit.id}: merge commit recorded as {args.landed_as}")
    return 0


def cmd_carry(args: argparse.Namespace, inst: Installation) -> int:
    """Carry a unit as the round would; `--dry-run` writes nothing, `--repair` carries a unit
    recorded merged with a commit that is not on the default branch, and `--landed-as <sha>`
    records the commit that carries its work. Exit 1 when the unit is refused."""
    store = run_support.store_for(inst)
    unit = next((u for u in store.all() if u.id == args.unit), None)
    if unit is None:
        _say(f"abk carry: no unit {args.unit!r}", error=True)
        return 2
    if args.landed_as:
        return _landed_as(args, inst, unit)

    repo, trunk = inst.checkouts[unit.repo], trunk_of(unit.repo)
    sha = carried_commit(unit)
    if args.repair:
        if unit.state != MERGED or sha is None:
            _say(f"{unit.id} is {unit.state}; --repair is for a unit recorded merged")
            return 1
        if merged_on_default(repo, sha, trunk):
            _say(
                f"{unit.id}: its commit {sha} is on the default branch ({trunk}); nothing to carry"
            )
            return 1
    elif unit.state != HELD or unit.cause is not Cause.LANDED_OFF_DEFAULT:
        _say(f"{unit.id} is {unit.state}, not held for landing off the default branch")
        return 1
    if sha is None:
        _say(f"{unit.id}: no commit recorded to carry")
        return 1
    if args.dry_run:
        _say(f"would carry {unit.id}: cherry-pick {sha} onto {trunk} as {carry_branch(unit.id)}")
        return 0

    forge, repo_id = inst.forge_of(unit.repo)
    try:
        done = carry_unit(
            store,
            unit,
            forge=forge,
            repo_id=repo_id,
            repo=repo,
            default_branch=trunk,
            worktrees=inst.worktree_root,
            claim=build_claim(inst.locks_dir),
            resolve=run_support.repo_resolver(inst, unit.id, unit.repo),
            repo_config=inst.repo(unit.repo),
            turn=lambda: run_support.repo_turn(inst, unit.repo),
            merge_record=lambda each: run_support.merge_record_of(inst, each),
            resume=run_support.thread_resumer(inst, store),
            hold=args.repair,
        )
    except (BranchBusy, RestackConflict) as error:
        _say(f"{unit.id}: not carried — {error}", error=True)
        return 1
    except AGENT_UNAVAILABLE as error:
        _say(f"{unit.id}: not carried, the model is unavailable ({error})", error=True)
        return 1
    except Exception as error:  # noqa: BLE001 — reported, and the carry can be run again
        _say(f"{unit.id}: carry failed — {type(error).__name__}: {error}", error=True)
        return 1
    if not done:
        _say(f"{unit.id} changed while it was being checked; run abk carry again")
        return 1
    _say(f"{unit.id}: carried onto {trunk}")
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("carry", help="carry a unit that landed off the default branch onto it")
    parser.add_argument("unit", help="the unit id, e.g. add-marker/1")
    parser.add_argument(
        "--dry-run", action="store_true", help="print the commit and the branch; write nothing"
    )
    parser.add_argument(
        "--repair",
        action="store_true",
        help="carry a unit recorded merged whose commit is not on the default branch",
    )
    parser.add_argument(
        "--landed-as",
        metavar="SHA",
        default="",
        help="record this commit of the default branch as the unit's merge commit",
    )
    parser.set_defaults(func=cmd_carry)
