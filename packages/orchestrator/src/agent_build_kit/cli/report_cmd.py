"""`abk report`: tokens, cost and time from the usage ledger, by any grouping."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import spans
from agent_build_kit.pipeline.archive import last_merged_at
from agent_build_kit.pipeline.carry import carried_commit
from agent_build_kit.pipeline.health_thresholds import evaluate_thresholds
from agent_build_kit.pipeline.review_revert import reverts_merge, reverts_pull_request
from agent_build_kit.pipeline.shell import commit_id, git
from agent_build_kit.pipeline.trusted_cost import RevertLookup, Verdict, sort_changes
from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.usage_forecast_record import FORECASTS_NAME
from agent_build_kit.pipeline.usage_ledger import LEDGER_NAME
from agent_build_kit.pipeline.usage_report import (
    GROUPINGS,
    build_context_report,
    build_report,
    build_wait_report,
    daily_spend_by_role,
    render_context,
    render_json,
    render_table,
    render_waits,
)
from agent_build_kit.pipeline.verdict_record import VERDICTS
from agent_build_kit.pipeline.wait_log import DECISIONS_NAME


def _trunk_of(checkout: Path, branch: str) -> str:
    """`origin/<branch>` when the checkout holds it (nothing is fetched), else the local branch."""
    return f"origin/{branch}" if commit_id(checkout, f"origin/{branch}") else branch


def _revert_lookup(inst: Installation, trunks: dict[str, str]) -> RevertLookup:
    """The search for a revert of a merged unit in its repo's checkout: by its merge commit, else
    by its pull request; None when it cannot be searched."""

    def lookup(unit: StoredUnit, until: datetime) -> bool | None:
        checkout = inst.checkouts.get(unit.repo)
        if checkout is None or unit.repo not in trunks:
            return None
        forge, identity = inst.forge_of(unit.repo)
        trunk = trunks[unit.repo]
        number = unit.pr if unit.pr is not None else next((p.number for p in unit.pulls), None)
        commit = carried_commit(unit)
        if commit:
            return reverts_merge(
                checkout,
                trunk=trunk,
                merge_commit=commit,
                repo=identity,
                pr=number or 0,
                until=until,
            )
        since = last_merged_at(unit)
        if number is None or since is None:
            return None
        return reverts_pull_request(
            checkout,
            trunk=trunk,
            forge=forge,
            repo=identity,
            pr=number,
            since=since,
            until=until,
        )

    return lookup


def _cell(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}"


def _render_trusted(document: dict) -> str:
    lines = ["changes by verdict (count, cost USD):"]
    for verdict, figures in document["by_verdict"].items():
        lines.append(f"  {verdict}: {figures['count']}, {_cell(figures['cost'])}")
    for change in document["changes"]:
        lines.append(
            f"  {change['verdict']} {change['change']} merged {change['merged_at'][:10]}"
            f" cost {_cell(change['cost'])}"
        )
    for name in ("latest", "previous"):
        window = document[name]
        lines.append(
            f"{name} window: cost per trusted change {_cell(window['cost_per_trusted_change'])}"
            f" over {window['costed']} costed, {window['uncosted']} uncosted"
        )
    lines.append(
        f"pending: {document['pending_count']} changes, {_cell(document['pending_cost'])} USD"
    )
    if document["unchecked"]:
        lines.append("unchecked: " + ", ".join(document["unchecked"]))
    for repo, read in document["repos"].items():
        lines.append(f"repo {repo}: read {read['ref']}, newest commit {read['newest_commit']}")
    for window in document["lacking"]:
        lines.append(f"the {window} window has no costed trusted change")
    if not document["breaches"]:
        lines.append("no threshold is breached")
    for breach in document["breaches"]:
        lines.append(
            f"BREACH {breach['signal']}: observed {breach['observed']:.2f}, limit {breach['limit']}"
        )
        lines.append(f"  correction: {breach['correction']}")
        lines.extend(f"  {item}" for item in breach["evidence"])
    return "\n".join(lines)


def _trusted(args: argparse.Namespace, inst: Installation) -> int:
    units = UnitStore(inst.state_dir / "units.json").all()
    ledger = inst.state_dir / LEDGER_NAME
    health = inst.config.health
    now = spans.clock.now()
    by_change = build_report(ledger, units, group_by="change")
    costs = {row.key: row.measured.cost_usd for row in by_change.rows}
    trunks: dict[str, str] = {}
    repos: dict[str, dict[str, str]] = {}
    for name, checkout in inst.checkouts.items():
        if not checkout.is_dir():
            continue
        trunk = _trunk_of(checkout, inst.repo(name).default_branch)
        trunks[name] = trunk
        newest = git(checkout, "log", "-1", "--format=%cI", trunk, check=False).stdout.strip()
        repos[name] = {"ref": trunk, "newest_commit": newest}
    found = sort_changes(
        units, costs, _revert_lookup(inst, trunks), now=now, days=health.trusted_days
    )
    report = evaluate_thresholds(daily_spend_by_role(ledger, units), found, units, health, now=now)
    by_verdict = {}
    for verdict in Verdict:
        mine = [c for c in found.changes if c.verdict == verdict]
        by_verdict[verdict.value] = {
            "count": len(mine),
            "cost": sum(c.cost for c in mine if c.cost is not None),
        }
    document = {
        **found.model_dump(mode="json"),
        "by_verdict": by_verdict,
        "repos": repos,
        "breaches": [b.model_dump(mode="json") for b in report.breaches],
        "lacking": list(report.lacking),
    }
    print(json.dumps(document, indent=2) if args.json else _render_trusted(document))
    return 0


def cmd_report(args: argparse.Namespace, inst: Installation) -> int:
    try:
        since = datetime.fromisoformat(args.since) if args.since else None
    except ValueError:
        print(f"--since: {args.since!r} is not a date (YYYY-MM-DD)")
        return 2
    if args.trusted:
        if args.waits or args.context:
            print("--trusted: one report at a time (not with --waits or --context)")
            return 2
        return _trusted(args, inst)
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
    parser.add_argument("--trusted", action="store_true", help="cost per trusted change, not cost")
    parser.set_defaults(func=cmd_report)
