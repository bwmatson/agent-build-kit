"""`abk policy`: the kit's recommended policy for a build agent, printed and compared."""

from __future__ import annotations

import argparse

from agent_build_kit.installation import Installation


def cmd_policy_patterns(args: argparse.Namespace, installation: Installation | None) -> int:
    raise NotImplementedError


def cmd_policy_show(args: argparse.Namespace, installation: Installation | None) -> int:
    raise NotImplementedError


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("policy", help="the recommended policy for a build agent")
    commands = parser.add_subparsers(dest="policy_command", required=True)
    patterns = commands.add_parser("patterns", help="print the recommended command globs")
    patterns.add_argument("--format", choices=("glob", "json", "yaml-list"), default="glob")
    patterns.add_argument("--class", dest="classes", action="append", default=[])
    patterns.add_argument("--extra", action="store_true")
    patterns.set_defaults(func=cmd_policy_patterns, needs_installation="optional")
    show = commands.add_parser("show", help="the recommendation, its gaps and its dialect")
    show.set_defaults(func=cmd_policy_show, needs_installation="optional")
