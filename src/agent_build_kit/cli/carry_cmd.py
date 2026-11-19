"""`abk carry`: carry a unit that landed off the default branch onto it, on demand
(spec: landed-off-default-units-are-carried)."""

from __future__ import annotations

import argparse
import sys

from agent_build_kit import run_support
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.carry import RestackConflict, carry, carry_branch
from agent_build_kit.pipeline.events import build_claim, record_landed
from agent_build_kit.pipeline.landing_check import merged_on_default
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import HELD, MERGED, trunk_of
from agent_build_kit.pipeline.workspaces import BranchBusy


def _say(text: str, *, error: bool = False) -> None:
    print(text, file=sys.stderr if error else sys.stdout)


def cmd_carry(args: argparse.Namespace, inst: Installation) -> int:
    """Carry a unit as the round would; `--dry-run` writes nothing, `--repair` carries a unit
    recorded merged with a commit that is not on the default branch, and `--landed-as <sha>`
    records the commit that carries its work. Exit 1 when the unit is refused."""
    store = run_support.store_for(inst)
    unit = next((u for u in store.all() if u.id == args.unit), None)
    if unit is None:
        _say(f"abk carry: no unit {args.unit!r}", error=True)
        return 2
    repo, trunk = inst.checkouts[unit.repo], trunk_of(unit.repo)
    sha = unit.merge_sha or next((p.merge_sha for p in reversed(unit.pulls) if p.merge_sha), None)

    if args.landed_as:
        if not merged_on_default(repo, args.landed_as, trunk):
            _say(f"{unit.id}: {args.landed_as} is not on the default branch ({trunk})")
            return 1
        if args.dry_run:
            _say(f"would record {args.landed_as} as the merge commit of {unit.id}")
            return 0
        if unit.state == HELD:
            resume = run_support.thread_resumer(inst, store)
            record_landed(
                store,
                unit,
                args.landed_as,
                lambda each: run_support.merge_record_of(inst, each),
                resume,
            )
        else:
            store.set_merge_record(unit.id, args.landed_as, None)
        _say(f"{unit.id}: merge commit recorded as {args.landed_as}")
        return 0

    repair = False
    if args.repair:
        if unit.state != MERGED or sha is None:
            _say(f"{unit.id} is {unit.state}; --repair is for a unit recorded merged")
            return 1
        if merged_on_default(repo, sha, trunk):
            _say(
                f"{unit.id}: its commit {sha} is on the default branch ({trunk}); nothing to carry"
            )
            return 1
        repair = True
    elif unit.state != HELD or unit.cause is not Cause.LANDED_OFF_DEFAULT:
        _say(f"{unit.id} is {unit.state}, not held for landing off the default branch")
        return 1
    if sha is None:
        _say(f"{unit.id}: no commit recorded to carry")
        return 1

    if args.dry_run:
        _say(f"would carry {unit.id}: cherry-pick {sha} onto {trunk} as {carry_branch(unit.id)}")
        return 0
    if repair:
        store.set_state(unit.id, HELD, cause=Cause.LANDED_OFF_DEFAULT, note="repair: carrying")

    resume = run_support.thread_resumer(inst, store)
    forge, repo_id = inst.forge_of(unit.repo)
    try:
        with build_claim(inst.locks_dir)(unit):
            carry(
                store,
                unit.id,
                forge=forge,
                repo_id=repo_id,
                repo=repo,
                default_branch=trunk,
                worktrees=inst.worktree_root,
                on_empty=lambda held, head: record_landed(
                    store, held, head, lambda each: run_support.merge_record_of(inst, each), resume
                ),
                resolve=run_support.repo_resolver(inst, unit.id, unit.repo),
                repo_config=inst.repo(unit.repo),
                turn=lambda: run_support.repo_turn(inst, unit.repo),
            )
    except (BranchBusy, RestackConflict) as error:
        _say(f"{unit.id}: not carried — {error}", error=True)
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
