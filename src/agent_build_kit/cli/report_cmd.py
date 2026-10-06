"""`abk report`: tokens, cost and time from the usage ledger, by any grouping."""

from __future__ import annotations

import argparse
from datetime import datetime

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.usage_ledger import LEDGER_NAME
from agent_build_kit.pipeline.usage_report import (
    GROUPINGS,
    build_report,
    render_json,
    render_table,
)


def cmd_report(args: argparse.Namespace, inst: Installation) -> int:
    try:
        since = datetime.fromisoformat(args.since) if args.since else None
    except ValueError:
        print(f"--since: {args.since!r} is not a date (YYYY-MM-DD)")
        return 2
    report = build_report(
        inst.state_dir / LEDGER_NAME,
        UnitStore(inst.state_dir / "units.json").all(),
        group_by=args.by,
        since=since,
        change=args.change,
        unit=args.unit,
        include_estimates=args.include_estimates,
    )
    print(render_json(report) if args.json else render_table(report))
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("report", help="token, cost and time use from the usage ledger")
    parser.add_argument("--by", choices=GROUPINGS, default="unit")
    parser.add_argument("--since", default=None, help="only calls on or after this date")
    parser.add_argument("--change", default=None)
    parser.add_argument("--unit", default=None)
    parser.add_argument("--include-estimates", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.set_defaults(func=cmd_report)
