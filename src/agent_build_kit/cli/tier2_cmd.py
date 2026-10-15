"""`abk tier2`: the tier 2 splits of a repo."""

from __future__ import annotations

import argparse
import subprocess
from collections.abc import Callable

from agent_build_kit.installation import Installation


def cmd_tier2_check(
    args: argparse.Namespace,
    installation: Installation | None,
    *,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> int:
    raise NotImplementedError


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("tier2", help="a repo's tier 2 splits")
    commands = parser.add_subparsers(dest="tier2_command", required=True)
    check = commands.add_parser("check", help="list each split and report overlaps; runs no test")
    check.add_argument("repo", nargs="?", help="the repo (default: every repo)")
    check.set_defaults(func=cmd_tier2_check)
