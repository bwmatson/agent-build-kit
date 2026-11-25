"""`abk outlines`: each outline's distance, and with `--overlaps` the changes it overlaps."""

from __future__ import annotations

import argparse

from agent_build_kit import run_support
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import outlines


def _line(reading: outlines.Reading) -> str:
    parts = [reading.outline.name]
    if reading.cycle:
        parts.append("cycle: " + " -> ".join(reading.cycle))
    else:
        parts.append(f"distance {reading.distance}")
    parts += [f"waits on {t} group {g}: {n} units" for t, g, n in reading.ahead]
    parts += [f"{name}: not found" for name in reading.not_found]
    parts += [f"unreadable: {line}" for line in reading.outline.unparsed]
    if reading.ready:
        parts.append("ready to detail")
    return "  ".join(parts)


def cmd_outlines(args: argparse.Namespace, inst: Installation) -> int:
    """Print each outline with its distance, nearest first; `args.overlaps` adds the overlaps."""
    for reading in outlines.readings(inst, run_support.store_for(inst).all()):
        print(_line(reading))
    if args.overlaps:
        for found in outlines.overlaps(inst):
            flag = "  promote earlier" if found.promote_earlier else ""
            print(f"{found.change} overlaps {found.outline}  reworks {found.reworks}{flag}")
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser(
        "outlines",
        help="report each outline's distance and which are ready to detail",
        description=(
            "Report each outline's distance: the units ahead of it that are not yet in review "
            "or merged. With --overlaps, also the detailed changes whose paths overlap an "
            "outline's. Reads only; makes no model call."
        ),
    )
    parser.add_argument("--overlaps", action="store_true", help="list overlapping changes")
    parser.set_defaults(func=cmd_outlines)
