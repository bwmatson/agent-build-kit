"""`abk replay review`: the recordings held for review, and keeping or deleting each."""

from __future__ import annotations

import argparse
import sys

from agent_build_kit.installation import Installation
from agent_build_kit.replay import review
from agent_build_kit.replay.models import RequestSummary, describe_difference


def _summary(summary: RequestSummary) -> str:
    query = f"?{summary.query}" if summary.query else ""
    return f"{summary.method} {summary.path}{query} ({summary.body_size} bytes)"


def _show(held: review.Waiting) -> None:
    cassette = held.cassette
    print(f"  {held.name}")
    print(f"    test: {cassette.test_id}, call {cassette.call_index}")
    print(f"    why: {cassette.review_reason}")
    print(f"    waiting: {_summary(cassette.request)}")
    if held.replacement is not None:
        print(f"    now: {_summary(held.replacement.request)}")
        print(f"    differs: {describe_difference(cassette.request, held.replacement.request)}")


def cmd_review(args: argparse.Namespace, inst: Installation) -> int:
    found = review.directories(inst.repos, inst.checkouts)
    if not found:
        print("no repository has a tests.replay section")
        return 1 if args.keep or args.delete else 0
    missing = 0
    for action, names in ((review.keep, args.keep), (review.delete, args.delete)):
        for name in names:
            if not any(action(directory, name) for directory, _ in found.values()):
                print(f"abk replay: no cassette waits as {name}", file=sys.stderr)
                missing += 1
    if args.keep or args.delete:
        return 1 if missing else 0
    for repo, (directory, _) in found.items():
        if held := review.waiting(directory):
            print(f"{repo}: {len(held)} waiting for review")
            for each in held:
                _show(each)
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("replay", help="the recorded calls of tier-2 tests (review)")
    actions = parser.add_subparsers(dest="action", required=True)
    command = actions.add_parser(
        "review", help="list the recordings waiting for review; decide with --keep or --delete"
    )
    command.add_argument(
        "--keep", action="append", default=[], metavar="NAME", help="clear the mark"
    )
    command.add_argument("--delete", action="append", default=[], metavar="NAME", help="remove it")
    command.set_defaults(func=cmd_review)
