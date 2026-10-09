"""`abk`: the command line the timers, the operator and the agents use.

Every subcommand lives in a module under this package that exposes
`register(sub)`; a command's parser sets `func` (called as
`func(args, installation)`) and, when the command does not need an
installation (it creates one, or works on a checkout alone),
`needs_installation=False` — or `"optional"`, in which case a missing
abk.yaml is not an error.
"""

from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

from agent_build_kit import __version__
from agent_build_kit.config import ConfigError
from agent_build_kit.installation import load_installation

# Import order is the help order.
COMMAND_MODULES = (
    "agent_build_kit.cli.pipeline",
    "agent_build_kit.cli.attach",
    "agent_build_kit.cli.init",
    "agent_build_kit.cli.doctor",
    "agent_build_kit.cli.config_cmd",
    "agent_build_kit.cli.scrub",
    "agent_build_kit.cli.changelog_cmd",
    "agent_build_kit.cli.tracks",
    "agent_build_kit.cli.telemetry_cmd",
    "agent_build_kit.cli.report_cmd",
    "agent_build_kit.cli.serve_cmd",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="abk", description=__doc__)
    parser.add_argument("--version", action="version", version=f"abk {__version__}")
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="the abk.yaml to use (default: ABK_CONFIG, or the nearest one above the cwd)",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name in COMMAND_MODULES:
        try:
            module = importlib.import_module(name)
        except ModuleNotFoundError as error:
            if error.name != name:
                raise
            continue
        module.register(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    needs = getattr(args, "needs_installation", True)
    installation = None
    if needs:
        try:
            installation = load_installation(args.config)
        except ConfigError as error:
            if needs != "optional":
                print(f"abk: {error}", file=sys.stderr)
                return 2
    return int(args.func(args, installation))
