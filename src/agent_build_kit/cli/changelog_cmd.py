"""`abk changelog check [PATH]`: the changelog's form, for any repo the pipeline builds."""

from __future__ import annotations

import argparse

from agent_build_kit.installation import Installation


def cmd_changelog_check(args: argparse.Namespace, inst: Installation | None) -> int:
    raise NotImplementedError


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("changelog", help="the changelog convention's checks")
    commands = parser.add_subparsers(dest="changelog_command", required=True)
    check = commands.add_parser("check", help="check a changelog's form")
    check.add_argument("path", nargs="?", default=None, help="default: the repo's setting")
    check.set_defaults(func=cmd_changelog_check, needs_installation="optional")
