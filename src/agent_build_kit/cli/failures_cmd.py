"""`abk failures`: the recorded failures of tests, with the conditions they failed under."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.failure_record import Evidenced, load_text
from agent_build_kit.pipeline.flakes import flake_record
from agent_build_kit.pipeline.product_defect import product_defect_record
from agent_build_kit.pipeline.untouched_failures import preexisting_record

# The files of a bundle whose content `--show` prints, in order.
SHOWN = ("context", "machine", "worktree")


class Row(Frozen):
    """One recorded failure of one test."""

    kind: str
    test: str
    unit: str
    at: datetime
    # The record itself, for the bundle it names and the conditions it ran under.
    entry: Evidenced = Evidenced()


def rows(inst: Installation) -> list[Row]:
    """Every failure recorded, a storm once for each test it names."""
    found: list[Row] = []
    for flake in flake_record(inst).entries():
        kind = "failing" if flake.failing else "flake"
        found.append(Row(kind=kind, test=flake.test, unit=flake.unit, at=flake.at, entry=flake))
    for storm in flake_record(inst).storms():
        found += [
            Row(kind="storm", test=test, unit=storm.unit, at=storm.at, entry=storm)
            for test in storm.tests
        ]
    for pre in preexisting_record(inst).entries():
        found.append(Row(kind="pre-existing", test=pre.test, unit=pre.unit, at=pre.at, entry=pre))
    for defect in product_defect_record(inst).entries():
        found.append(Row(kind="product-defect", test=defect.test, unit=defect.unit, at=defect.at))
    return found


def _line(kind: str, test: str, group: list[Row]) -> str:
    times = sorted(row.at for row in group)
    units = sorted({row.unit for row in group if row.unit})
    load = load_text(row.entry for row in group)
    parts = [
        f"{test}  {kind}",
        f"{len(group)} time{'' if len(group) == 1 else 's'}",
        f"first {times[0]:%Y-%m-%d} last {times[-1]:%Y-%m-%d}",
        f"units {', '.join(units)}" if units else "",
        load,
    ]
    return "  ".join(part for part in parts if part)


def _show(group: list[Row]) -> None:
    """The context, machine and worktree lines of the newest bundle any of `group` names."""
    named = sorted((row for row in group if row.entry.evidence), key=lambda row: row.at)
    if not named:
        print("no bundle is named by these records")
        return
    bundle = Path(named[-1].entry.evidence)
    print(f"newest bundle: {bundle}")
    for name in SHOWN:
        try:
            facts = json.loads((bundle / f"{name}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            print(f"{name}: not readable (the bundle may have been removed)")
            continue
        print(f"{name}: {json.dumps(facts)}")
    print(f"output: {bundle / 'output.txt'}")


def cmd_failures(args: argparse.Namespace, inst: Installation) -> int:
    """List the flakes, storms, pre-existing failures and product defects recorded, each test
    with its count, first and last time, units and load; `args.test` limits it to one test and
    `args.show` prints the newest bundle's context, machine and worktree lines."""
    found = [row for row in rows(inst) if args.test in (None, row.test)]
    groups: dict[tuple[str, str], list[Row]] = {}
    for row in found:
        groups.setdefault((row.kind, row.test), []).append(row)
    for (kind, test), group in groups.items():
        print(_line(kind, test, group))
    if args.show and found:
        _show(found)
    elif args.show:
        print(f"no failure of {args.test} is recorded")
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser(
        "failures",
        help="list the recorded failures of tests and the conditions they failed under",
        description=(
            "List the flakes, storms, pre-existing failures and product defects recorded, each "
            "test with how often it failed, when first and last, in which units and under what "
            "load. With TEST, only that test; with --show, the newest bundle's context, machine "
            "and worktree lines and the path of its output."
        ),
    )
    parser.add_argument("test", nargs="?", default=None, help="limit the listing to this test")
    parser.add_argument(
        "--show", action="store_true", help="print the newest bundle's lines and its output path"
    )
    parser.set_defaults(func=cmd_failures)
