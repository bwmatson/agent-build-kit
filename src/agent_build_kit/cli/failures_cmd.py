"""`abk failures`: the recorded failures of tests, with the conditions they failed under."""

from __future__ import annotations

import argparse

from agent_build_kit.installation import Installation


def cmd_failures(args: argparse.Namespace, inst: Installation) -> int:
    """List the flakes, storms, pre-existing failures and product defects recorded, each test
    with its count, first and last time, units and load; `args.test` limits it to one test and
    `args.show` prints the newest bundle's context, machine and worktree lines."""
    raise NotImplementedError
