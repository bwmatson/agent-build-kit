"""`abk outlines`: each outline's distance, and with `--overlaps` the changes it overlaps."""

from __future__ import annotations

import argparse

from agent_build_kit.installation import Installation


def cmd_outlines(args: argparse.Namespace, inst: Installation) -> int:
    """Print each outline with its distance, nearest first; `args.overlaps` adds the overlaps."""
    raise NotImplementedError
