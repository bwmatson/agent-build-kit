"""`abk red-check`: the tests step sees the build's red verdict on its worktree first."""

from __future__ import annotations

import argparse

from agent_build_kit.installation import Installation


def cmd_red_check(args: argparse.Namespace, inst: Installation) -> int:
    """Judge the worktree's tree as the build's red check judges a tests commit."""
    raise NotImplementedError


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser(
        "red-check", help="judge this unit worktree's new and changed tests as the build will"
    )
    parser.set_defaults(func=cmd_red_check)
