"""`abk review-plan`: show or clear the findings a model's review of a change's plan left
(spec: plan-review)."""

from __future__ import annotations

import argparse

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import plan_review


def cmd_show(args: argparse.Namespace, inst: Installation) -> int:
    review = plan_review.read_reviews(plan_review.record_path(inst)).get(args.change)
    if review is None:
        print(f"{args.change}: no plan review recorded")
        return 0
    if not review.findings:
        print(f"{args.change}: the plan review has no findings")
        return 0
    state = "cleared" if review.cleared else "held"
    print(f"{args.change}: plan review {state}, {len(review.findings)} finding(s)")
    for line in plan_review.finding_lines(review):
        print(f"  {line}")
    if review.note:
        print(f"note: {review.note}")
    return 0


def cmd_clear(args: argparse.Namespace, inst: Installation) -> int:
    count = plan_review.clear(inst, args.change, args.note)
    if not count:
        print(f"{args.change}: no findings to clear")
        return 0
    print(f"{args.change}: cleared {count} finding(s); the next tick starts its units")
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser(
        "review-plan", help="show or clear the findings of a change's plan review"
    )
    actions = parser.add_subparsers(dest="action", required=True)
    show = actions.add_parser("show", help="print each finding of a change's plan review")
    show.add_argument("change")
    show.set_defaults(func=cmd_show)
    cleared = actions.add_parser("clear", help="clear the findings that hold a change")
    cleared.add_argument("change")
    cleared.add_argument("--note", default="", help="why the findings are accepted; recorded")
    cleared.set_defaults(func=cmd_clear)
