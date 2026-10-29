"""`abk settle`: end the wait of a unit whose merged pull request has a check that will never
finish.

Spec: merged-waits-for-ci. A unit settles on its own once every check has completed; this is the
person's way out when one never will.
"""

from __future__ import annotations

import argparse
import sys

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.events import build_claim, settle_merged
from agent_build_kit.pipeline.units import SETTLING
from agent_build_kit.pipeline.workspaces import BranchBusy


def cmd_settle(args: argparse.Namespace, inst: Installation) -> int:
    """Accept a settling unit as merged, with the person's reason in its note."""
    # Late: the pipeline module imports the commands.
    from agent_build_kit.cli import pipeline as pipe

    store = pipe.store_for(inst)
    try:
        unit = store.get(args.unit)
    except KeyError:
        print(f"abk settle: no unit {args.unit!r}", file=sys.stderr)
        return 2
    if not args.accept:
        print(
            "abk settle: give --accept to end the wait and record the unit as merged",
            file=sys.stderr,
        )
        return 2
    try:
        # The unit's branch lock, as the poller's handlers take it: a tick running the failed
        # check's tests on the base holds it and writes the unit's next state.
        with build_claim(inst.locks_dir)(unit):
            current = store.get(unit.id)
            if current.state != SETTLING:
                print(f"abk settle: {current.id} is {current.state}, not settling", file=sys.stderr)
                return 1
            why = f": {args.reason}" if args.reason else ""
            settle_merged(
                store,
                current,
                lambda each: pipe.merge_record_of(inst, each),
                note=f"accepted as merged by a person{why}",
            )
    except BranchBusy:
        print(f"abk settle: a tick is handling {unit.id}; try again shortly", file=sys.stderr)
        return 1
    print(f"{unit.id}: merged (accepted while settling)")
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    settle = sub.add_parser(
        "settle", help="end the wait of a merged unit whose check will never finish"
    )
    settle.add_argument("unit", help="the unit id, e.g. add-marker/1")
    settle.add_argument(
        "--accept", action="store_true", help="record the unit as merged without its checks"
    )
    settle.add_argument(
        "--reason", metavar="TEXT", default="", help="why, kept in the unit's history"
    )
    settle.set_defaults(func=cmd_settle)
