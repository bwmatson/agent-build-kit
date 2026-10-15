"""`abk scrub-store`: replace home-directory paths in the stored unit text."""

from __future__ import annotations

import argparse

from agent_build_kit.installation import Installation

HELP = "replace home-directory paths in the stored unit text"


def cmd_scrub_store(args: argparse.Namespace, inst: Installation) -> int:
    raise NotImplementedError


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("scrub-store", help=HELP, description=HELP)
    parser.add_argument("--apply", action="store_true", help="rewrite the store (default: dry run)")
    parser.set_defaults(func=cmd_scrub_store)
