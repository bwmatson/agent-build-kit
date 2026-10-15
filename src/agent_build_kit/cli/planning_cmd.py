"""`abk planning split`: move a repo's changes, specs and unit records to another planning repo.

A dry run unless `--apply` is given: the plan is printed and nothing is written in either
installation. Exit 0 when nothing is refused, 1 when anything is, 2 for a usage problem."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agent_build_kit.config import CONFIG_FILENAME
from agent_build_kit.installation import Installation
from agent_build_kit.split import copy, scrubbing
from agent_build_kit.split.config_edit import ConfigEditError, add_repo_entry
from agent_build_kit.split.select import (
    SplitPlan,
    SplitUsageError,
    load_destination,
    plan_split,
)

HELP = "move a repo's changes, specs and unit records to another planning repo"


def _fail(message: str) -> int:
    print(f"abk: {message}", file=sys.stderr)
    return 2


def _counts(source: Installation, plan: SplitPlan, entries: int) -> list[str]:
    return [
        f"  changes: {len(plan.changes_moved)}",
        f"  archive entries: {len(plan.archive_moved)}",
        f"  specs: {len(plan.specs_moved)}",
        f"  units: {len(plan.units_moved)}",
        f"  plan records: {len(copy.moved_plan_records(source, plan))}",
        f"  config entries: {entries}",
    ]


def _removals(source: Installation, plan: SplitPlan) -> list[str]:
    return [
        *(f"  would remove change {name}" for name in plan.changes_moved),
        *(f"  would remove archive entry {name}" for name in plan.archive_moved),
        *(f"  would remove spec {name}" for name in plan.specs_moved),
        *(f"  would remove unit {name}" for name in plan.units_moved),
        *(f"  would remove plan record {name}" for name in copy.moved_plan_records(source, plan)),
    ]


def cmd_planning_split(args: argparse.Namespace, source: Installation) -> int:
    if args.apply and args.dry_run:
        return _fail("--dry-run and --apply cannot be given together")
    if args.apply and args.remove:
        return _fail("--remove with --apply is not available yet")
    try:
        destination = load_destination(Path(args.to), source)
        plan = plan_split(
            source,
            args.repo,
            args.project,
            args.allow_mixed,
            args.spec,
            destination_repos=set(destination.repos),
        )
    except SplitUsageError as error:
        return _fail(str(error))

    source_config = source.root / CONFIG_FILENAME
    destination_config = destination.root / CONFIG_FILENAME
    refusals = [refusal.line for refusal in plan.refusals]
    entry = None
    try:
        entry = add_repo_entry(source_config, destination_config, args.repo, write=False)
    except ConfigEditError as error:
        refusals.append(str(error))
    found = copy.preflight(source, destination, plan, scrub=args.scrub, remove=args.remove)
    refusals += found.errors

    selection = f"repo {args.repo}" + (f", project {plan.project}" if plan.project else "")
    print(f"source: {source.root}")
    print(f"destination: {destination.root}")
    print(f"selection: {selection}")
    print("plan:")
    entries = 0 if entry is None or entry.already_declared else 1
    print("\n".join(_counts(source, plan, entries)))
    if entry is not None and entry.already_declared:
        print(f"  repo {args.repo} is already declared in the destination")
    if entry is not None and entry.missing_consumes:
        print(f"  consumes not declared in the destination: {', '.join(entry.missing_consumes)}")
    if plan.uncommitted is None:
        print("uncommitted: no git information (the source is not under git)")
    else:
        print(f"uncommitted files read: {len(plan.uncommitted)}")
        print("\n".join(f"  {line}" for line in plan.uncommitted))
    if args.scrub:
        counts = scrubbing.scrub_counts(source, plan)
        print(
            f"scrub: {counts.files} files, {counts.records} records, "
            f"{counts.substitutions} substitutions"
        )
    for warning in found.warnings:
        print(f"warning: {warning}")
    for line in refusals:
        print(f"refused: {line}")
    if args.remove:
        print("\n".join(_removals(source, plan)))

    if refusals:
        print("nothing was written; settle the refusals above, then run again")
        return 1
    if not args.apply:
        print("nothing was written; run again with --apply to carry the plan out")
        return 0
    report = copy.carry_out(source, destination, plan, scrub=args.scrub)
    add_repo_entry(source_config, destination_config, args.repo)
    print(
        f"copied {report.files_copied} files ({report.files_unchanged} unchanged), "
        f"{report.units_imported} unit records, {report.plans_written} plan records"
    )
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    planning = sub.add_parser("planning", help="work on the planning repo itself")
    commands = planning.add_subparsers(dest="planning_command", required=True)
    split = commands.add_parser("split", help=HELP, description=__doc__)
    split.add_argument("--repo", required=True, help="the repo whose changes move")
    split.add_argument("--project", help="move only the groups of this project of the repo")
    split.add_argument("--to", required=True, help="the destination planning repo's directory")
    split.add_argument(
        "--allow-mixed", help="`source` keeps changes of several repos, `destination` moves them"
    )
    split.add_argument("--spec", action="append", default=[], help="a capability to move anyway")
    split.add_argument("--scrub", action="store_true", help="strip installation names from text")
    split.add_argument("--remove", action="store_true", help="remove what moved from the source")
    split.add_argument("--apply", action="store_true", help="carry the plan out")
    split.add_argument("--dry-run", action="store_true", help="print the plan only (the default)")
    split.set_defaults(func=cmd_planning_split)
