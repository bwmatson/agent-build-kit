"""`abk tests report`: the five figures of a repository's tests."""

from __future__ import annotations

import argparse
from datetime import datetime

from agent_build_kit.installation import Installation


def cmd_tests_report(
    args: argparse.Namespace, installation: Installation | None, *, now: datetime | None = None
) -> int:
    """Print the figures of `args.repo` (every repository when None) from `args.since` (seven
    days before `now` when None); non-zero for an unknown repository or a date that does not
    parse."""
    raise NotImplementedError


def register(sub: argparse._SubParsersAction) -> None:
    raise NotImplementedError
