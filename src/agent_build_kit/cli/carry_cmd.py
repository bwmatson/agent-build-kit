"""`abk carry`: carry a unit that landed off the default branch onto it, on demand
(spec: landed-off-default-units-are-carried)."""

from __future__ import annotations

import argparse

from agent_build_kit.installation import Installation


def cmd_carry(args: argparse.Namespace, inst: Installation) -> int:
    """Carry a unit as the round would; `--dry-run` writes nothing, `--repair` carries a unit
    recorded merged with a commit that is not on the default branch, and `--landed-as <sha>`
    records the commit that carries its work. Exit 1 when the unit is refused."""
    raise NotImplementedError


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("carry", help="carry a unit that landed off the default branch onto it")
    parser.add_argument("unit", help="the unit id, e.g. add-marker/1")
    parser.add_argument(
        "--dry-run", action="store_true", help="print the commit and the branch; write nothing"
    )
    parser.add_argument(
        "--repair",
        action="store_true",
        help="carry a unit recorded merged whose commit is not on the default branch",
    )
    parser.add_argument(
        "--landed-as",
        metavar="SHA",
        default="",
        help="record this commit of the default branch as the unit's merge commit",
    )
    parser.set_defaults(func=cmd_carry)
