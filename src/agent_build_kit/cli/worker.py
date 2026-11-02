"""`abk worker`: one piece of work run as its own process."""

from __future__ import annotations

import argparse

from agent_build_kit.installation import Installation


def cmd_worker_build(args: argparse.Namespace, inst: Installation) -> int:
    """Run the unit's graph to its next wait under its branch lock, record the outcome, release
    the lock, touch `runs/wake` and exit 0; non-zero only for a crash before an outcome."""
    raise NotImplementedError
