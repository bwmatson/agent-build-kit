"""`abk attach release`: end a chat's attachment to a unit without the server."""

from __future__ import annotations

import argparse
from typing import Any

from agent_build_kit.installation import Installation


def cmd_attach_release(args: argparse.Namespace, inst: Installation) -> int:
    """Commit (`--commit MESSAGE`) or discard (`--discard`) the unit's uncommitted changes and
    release its lease in one operation; refuse a dirty tree given neither."""
    raise NotImplementedError


def register(sub: Any) -> None:
    attach = sub.add_parser("attach", help="a chat's attachment to a unit")
    verbs = attach.add_subparsers(dest="attach_command", required=True)
    release = verbs.add_parser("release", help="commit or discard a unit's chat changes")
    release.add_argument("unit")
    release.add_argument("--commit", metavar="MESSAGE", default=None)
    release.add_argument("--discard", action="store_true")
    release.set_defaults(func=cmd_attach_release)
