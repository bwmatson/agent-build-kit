"""`abk report`: tokens, cost and time from the usage ledger, by any grouping."""

from __future__ import annotations

import argparse

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.usage_report import GROUPINGS


def cmd_report(args: argparse.Namespace, inst: Installation) -> int:
    raise NotImplementedError


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("report", help="token, cost and time use from the usage ledger")
    parser.add_argument("--by", choices=GROUPINGS, default="unit")
    parser.add_argument("--since", default=None, help="only calls on or after this date")
    parser.add_argument("--change", default=None)
    parser.add_argument("--unit", default=None)
    parser.add_argument("--include-estimates", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.set_defaults(func=cmd_report)
