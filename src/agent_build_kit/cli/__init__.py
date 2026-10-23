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
from agent_build_kit import settings as settings_module
from agent_build_kit.config import ConfigError
from agent_build_kit.installation import load_installation
from agent_build_kit.pipeline.planning_sync import live_notice

# Commands that write the pipeline's state: from a working copy whose installation is live in the
# pipeline worktree they refuse, unless a config is named. `status` only says where it is.
WRITES_STATE = frozenset({"tick", "track", "verify", "archive"})

# Import order is the help order.
COMMAND_MODULES = (
    "agent_build_kit.cli.pipeline",
    "agent_build_kit.cli.explain_cmd",
    "agent_build_kit.cli.attach",
    "agent_build_kit.cli.init",
    "agent_build_kit.cli.doctor",
    "agent_build_kit.cli.config_cmd",
    "agent_build_kit.cli.project_cmd",
    "agent_build_kit.cli.planning_cmd",
    "agent_build_kit.cli.scrub",
    "agent_build_kit.cli.changelog_cmd",
    "agent_build_kit.cli.tracks",
    "agent_build_kit.cli.telemetry_cmd",
    "agent_build_kit.cli.report_cmd",
    "agent_build_kit.cli.usage_cmd",
    "agent_build_kit.cli.redact_history_cmd",
    "agent_build_kit.cli.scrub_store_cmd",
    "agent_build_kit.cli.serve_cmd",
    "agent_build_kit.cli.pr_cmd",
    "agent_build_kit.cli.replay_cmd",
    "agent_build_kit.cli.policy_cmd",
    "agent_build_kit.cli.e2e_cmd",
    "agent_build_kit.cli.install_config",
    "agent_build_kit.cli.manual_cmd",
    "agent_build_kit.cli.review_cmd",
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
    explicit = args.config is not None or settings_module.settings.config is not None
    if needs:
        try:
            installation = load_installation(args.config)
        except ConfigError as error:
            if needs != "optional":
                print(f"abk: {error}", file=sys.stderr)
                return 2
    if installation is not None and (args.command == "status" or args.command in WRITES_STATE):
        if notice := live_notice(installation, args.command, explicit=explicit):
            refused = not explicit and args.command != "status"
            print(notice, file=sys.stderr if refused else sys.stdout)
            if not explicit:
                return 2 if refused else 0
    return int(args.func(args, installation))
