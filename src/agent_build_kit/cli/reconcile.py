"""`abk reconcile`: compare units' recorded pull requests with the forge, now.

Spec: pr-reconcile. The tick runs the same pass each time; this is the way to run it at once, to
see what it would do, or to record a merge the forge confirms.
"""

from __future__ import annotations

import argparse
import sys

from agent_build_kit.forges.base import listed_pull
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.pr_reconcile import reconcile
from agent_build_kit.pipeline.unit_store import KEEP
from agent_build_kit.pipeline.units import SETTLING


def accept(inst: Installation, unit_id: str) -> int:
    """Record the merge of a unit's pull request, once the forge itself confirms it."""
    # Late: the pipeline module imports the commands.
    from agent_build_kit.cli import pipeline as pipe

    store = pipe.store_for(inst)
    try:
        unit = store.get(unit_id)
    except KeyError:
        print(f"abk reconcile: no unit {unit_id!r}", file=sys.stderr)
        return 2
    if unit.state == SETTLING:
        print(f"abk reconcile: {unit.id} is settling; it has recorded its merge", file=sys.stderr)
        return 1
    if unit.pr is None:
        print(f"abk reconcile: {unit.id} records no pull request", file=sys.stderr)
        return 1
    forge, repo_id = inst.forge_of(unit.repo)
    if not forge.merge_commit(repo_id, unit.pr):
        pull = listed_pull(forge, repo_id, unit.branch or f"spec/{unit.id}", unit.pr)
        shown = pull.state if pull else "not listed"
        print(
            f"abk reconcile: refused, #{unit.pr} is {shown} on the forge, not merged",
            file=sys.stderr,
        )
        return 1
    if not pipe.dispatch_for(inst, store)("merged", unit.pr, repo=unit.repo):
        print(f"abk reconcile: a tick is handling {unit.id}; try again shortly", file=sys.stderr)
        return 1
    recorded = store.get(unit.id)
    store.set_state(
        recorded.id,
        recorded.state,
        note=f"merge of #{unit.pr} recorded by abk reconcile --accept",
        cause=KEEP,
    )
    print(f"{unit.id}: merged (accepted, #{unit.pr} merged on the forge)")
    return 0


def cmd_reconcile(args: argparse.Namespace, inst: Installation) -> int:
    if args.accept:
        return accept(inst, args.accept)
    from agent_build_kit.cli import pipeline as pipe

    store = pipe.store_for(inst)
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
