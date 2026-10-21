"""`abk explain <unit> [--at TIME]`: why a unit was admitted, held or paused, from the records."""

from __future__ import annotations

import argparse

from agent_build_kit.installation import Installation


def cmd_explain(args: argparse.Namespace, inst: Installation) -> int:
    """Print why `args.unit` was admitted, held or paused at `args.at` (an ISO time, or None for
    the latest record)."""
    raise NotImplementedError
