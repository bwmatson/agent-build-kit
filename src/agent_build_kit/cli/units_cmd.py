"""`abk units`: commands over the unit store as a whole.

`prune --unplanned` is the sweep of `unplanned` units on demand (spec: unplanned-sweep): the same
eligibility the tick applies at the end of a pass, with a dry run that lists what would go and, for
each unit that stays, the first condition it fails.
"""

from __future__ import annotations

import argparse
import sys

from agent_build_kit.cli.pipeline import store_for
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import spans
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import UnitState
from agent_build_kit.pipeline.unplanned_sweep import Verdict, eligibility, live_changes
from agent_build_kit.trackers.folders import archived_entries
from agent_build_kit.trackers.tick_step import tracker_pass


def _repointing(verdict: Verdict) -> str:
    """What a removal does to the units that name the one removed, for the line that says so."""
    if not verdict.repoint:
        return ""
    named = ", ".join(f"{each.referrer} ({each.field})" for each in verdict.repoint)
    return f"; repoints {named} to {', '.join(verdict.successors)}"


def cmd_units_prune(args: argparse.Namespace, inst: Installation) -> int:
    """List the `unplanned` units that would be removed and why each other stays (`--dry-run`),
    or remove the eligible ones and list the rest. Exit 1 when there is no changes folder."""
    store: UnitStore = store_for(inst)
    tombstones = [unit for unit in store.all() if unit.state == UnitState.UNPLANNED]
    if not tombstones:
        print("no unplanned units")
        return 0
    live = live_changes(inst.changes_dir)
    if live is None:
        print(f"no changes folder at {inst.changes_dir}: nothing is removed", file=sys.stderr)
        return 1
    configured, reconciled = tracker_pass(inst)
    verdicts = eligibility(
        store.all(),
        active_changes=live,
        archived_changes=set(archived_entries(inst.changes_dir)),
        pass_started=spans.clock.now(),
        tracker_configured=configured,
        tracker_reconciled=reconciled,
    )
    cleared = {uid: found.successors for uid, found in verdicts.items() if found.eligible}
    removed = set() if args.dry_run else set(store.remove_swept(cleared))
    for uid in sorted(verdicts):
        found = verdicts[uid]
        if found.eligible:
            verb = "would remove" if args.dry_run else "removed" if uid in removed else "kept"
            print(f"{verb} {uid}{_repointing(found)}")
        else:
            print(f"kept {uid}: {found.reason}")
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("units", help="commands over the unit store")
    commands = parser.add_subparsers(dest="units_command", required=True)
    prune = commands.add_parser(
        "prune",
        help="remove the units a plan dropped that nothing needs any more",
        description=(
            "Remove the `unplanned` units that hold no work, that no other unit needs, that a "
            "live unit carries, that a pass and the tracker have seen, and whose change keeps "
            "another unit. Prints each unit removed and, for each one kept, the first condition "
            "it fails."
        ),
    )
    prune.add_argument("--unplanned", action="store_true", required=True, help="the kind to prune")
    prune.add_argument(
        "--dry-run", action="store_true", help="list what would be removed; write nothing"
    )
    prune.set_defaults(func=cmd_units_prune)
