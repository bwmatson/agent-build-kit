"""`abk reconcile`: compare units' recorded pull requests with the forge, now.

Spec: pr-reconcile. The tick runs the same pass each time; this is the way to run it at once, to
see what it would do, or to record a merge the forge confirms.
"""

from __future__ import annotations

import argparse
import sys

from agent_build_kit.forges.base import listed_pull
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.events import build_claim
from agent_build_kit.pipeline.pr_reconcile import reconcile
from agent_build_kit.pipeline.unit_store import KEEP, StoredUnit, UnitStore
from agent_build_kit.pipeline.units import MERGED, SETTLING, branch_name
from agent_build_kit.pipeline.workspaces import BranchBusy

# The states whose unit has already recorded its merge: nothing is left to accept.
RECORDED = (SETTLING, MERGED)


def find_unit(store: UnitStore, unit_id: str) -> StoredUnit | None:
    """The named unit, or None after saying there is none."""
    try:
        return store.get(unit_id)
    except KeyError:
        print(f"abk reconcile: no unit {unit_id!r}", file=sys.stderr)
        return None


def accept(inst: Installation, store: UnitStore, unit_id: str) -> int:
    """Record the merge of a unit's pull request, once the forge itself confirms it."""
    # Late: the pipeline module imports the commands.
    from agent_build_kit.cli import pipeline as pipe

    unit = find_unit(store, unit_id)
    if unit is None:
        return 2
    if unit.state in RECORDED:
        print(
            f"abk reconcile: {unit.id} is {unit.state}; it has recorded its merge",
            file=sys.stderr,
        )
        return 1
    if unit.pr is None:
        print(f"abk reconcile: {unit.id} records no pull request", file=sys.stderr)
        return 1
    forge, repo_id = inst.forge_of(unit.repo)
    merged = forge.merge_commit(repo_id, unit.pr)
    if not merged:
        pull = listed_pull(forge, repo_id, branch_name(unit), unit.pr)
        shown = pull.state if pull else "not listed"
        print(
            f"abk reconcile: refused, #{unit.pr} is {shown} on the forge, not merged",
            file=sys.stderr,
        )
        return 1
    # The commit just confirmed is the one recorded: the merge record does not ask again.
    if not pipe.dispatch_for(inst, store)("merged", unit.pr, repo=unit.repo, merge_commit=merged):
        print(f"abk reconcile: a tick is handling {unit.id}; try again shortly", file=sys.stderr)
        return 1
    try:
        # The unit's branch lock, as `abk settle` takes it: a tick writes the unit's next state,
        # which a note written from an earlier read would undo.
        with build_claim(inst.locks_dir)(unit):
            recorded = store.get(unit.id)
            store.set_state(
                recorded.id,
                recorded.state,
                note=f"merge of #{unit.pr} recorded by abk reconcile --accept",
                cause=KEEP,
            )
    except BranchBusy:
        print(
            f"abk reconcile: {unit.id}: the merge is recorded, but a tick is handling the unit, "
            "so the note naming this command is not",
            file=sys.stderr,
        )
    print(f"{unit.id}: merged (accepted, #{unit.pr} merged on the forge)")
    return 0


def cmd_reconcile(args: argparse.Namespace, inst: Installation) -> int:
    # Late: the pipeline module imports the commands.
    from agent_build_kit.cli import pipeline as pipe

    if args.accept and (args.dry_run or args.unit):
        print(
            "abk reconcile: --accept takes its unit alone, with no UNIT argument or --dry-run",
            file=sys.stderr,
        )
        return 2
    store = pipe.store_for(inst)
    if args.accept:
        return accept(inst, store, args.accept)
    if args.unit and find_unit(store, args.unit) is None:
        return 2
    reconcile(
        store=store,
        state_dir=inst.state_dir,
        dispatch=pipe.dispatch_for(inst, store),
        only=args.unit,
        dry_run=args.dry_run,
    )
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    reconcile_parser = sub.add_parser(
        "reconcile", help="record a merge or close the forge shows that a unit has not recorded"
    )
    reconcile_parser.add_argument("unit", nargs="?", help="limit the pass to this unit")
    reconcile_parser.add_argument(
        "--dry-run", action="store_true", help="print what would be done and write nothing"
    )
    reconcile_parser.add_argument(
        "--accept",
        metavar="UNIT",
        help="record the merge of this unit's pull request, as the forge confirms it",
    )
    reconcile_parser.set_defaults(func=cmd_reconcile)
