"""`abk report`: tokens, cost and time from the usage ledger, by any grouping."""

from __future__ import annotations

import argparse
from datetime import datetime

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.usage_forecast_record import FORECASTS_NAME
from agent_build_kit.pipeline.usage_ledger import LEDGER_NAME
from agent_build_kit.pipeline.usage_report import (
    GROUPINGS,
    build_context_report,
    build_report,
    build_wait_report,
    render_context,
    render_json,
    render_table,
    render_waits,
)
from agent_build_kit.pipeline.verdict_record import VERDICTS
from agent_build_kit.pipeline.wait_log import DECISIONS_NAME


def cmd_report(args: argparse.Namespace, inst: Installation) -> int:
    try:
        since = datetime.fromisoformat(args.since) if args.since else None
    except ValueError:
        print(f"--since: {args.since!r} is not a date (YYYY-MM-DD)")
        return 2
    if args.waits:
        try:
            waits = build_wait_report(
                inst.state_dir / LEDGER_NAME,
                inst.state_dir / DECISIONS_NAME,
                UnitStore(inst.state_dir / "units.json").all(),
                group_by=args.by,
            )
        except ValueError as error:
            print(f"--waits: {error}")
            return 2
        print(render_json(waits) if args.json else render_waits(waits))
        return 0
    if args.context:
        print(
            render_context(
                build_context_report(
                    inst.state_dir / LEDGER_NAME,
                    UnitStore(inst.state_dir / "units.json").all(),
                    since=since,
                    change=args.change,
                    unit=args.unit,
                )
            )
        )
        return 0
    report = build_report(
        inst.state_dir / LEDGER_NAME,
        UnitStore(inst.state_dir / "units.json").all(),
        group_by=args.by,
        since=since,
        change=args.change,
        unit=args.unit,
        include_estimates=args.include_estimates,
        verdicts=inst.state_dir / VERDICTS,
        forecasts=inst.state_dir / FORECASTS_NAME,
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
    parser.add_argument("--waits", action="store_true", help="wall time by cause, not cost")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--context", action="store_true", help="context window use, not cost")
    parser.set_defaults(func=cmd_report)
