"""`abk review report`: the rates and the gates of each class, read-only."""

from __future__ import annotations

import argparse

from agent_build_kit.installation import Installation


def cmd_review_report(args: argparse.Namespace, inst: Installation) -> int:
    raise NotImplementedError


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("review", help="the review record")
    commands = parser.add_subparsers(dest="review_command", required=True)
    report = commands.add_parser(
        "report", help="print each class's rates and whether it clears the gates"
    )
    report.set_defaults(func=cmd_review_report)
