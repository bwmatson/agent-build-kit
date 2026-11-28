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
import importlib.metadata
import sys
from pathlib import Path
from pkgutil import extend_path
from typing import Any

from agent_build_kit import __version__
from agent_build_kit import settings as settings_module
from agent_build_kit.config import ConfigError
from agent_build_kit.installation import load_installation
from agent_build_kit.pipeline.planning_sync import live_notice

# The worker package holds the `worker` command's module.
__path__ = extend_path(__path__, __name__)

# Commands that write the pipeline's state: from a working copy whose installation is live in the
# pipeline worktree they refuse, unless a config is named. `status` only says where it is.
WRITES_STATE = frozenset({"tick", "track", "verify", "archive", "worker"})

# Import order is the help order.
COMMAND_MODULES = (
    "agent_build_kit.cli.pipeline",
    "agent_build_kit.cli.explain_cmd",
    "agent_build_kit.cli.failures_cmd",
    "agent_build_kit.cli.outlines_cmd",
    "agent_build_kit.cli.settle",
    "agent_build_kit.cli.reconcile",
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
    "agent_build_kit.cli.red_check_cmd",
    "agent_build_kit.cli.external_cmd",
    "agent_build_kit.cli.tracker_cmd",
    "agent_build_kit.cli.review_report",
    "agent_build_kit.cli.units_cmd",
    "agent_build_kit.cli.carry_cmd",
    "agent_build_kit.cli.review_plan_cmd",
    "agent_build_kit.cli.attention_cmd",
    "agent_build_kit.cli.db_cmd",
    "agent_build_kit.cli.tests_cmd",
)

# Commands a separately installed package registers: the entry-point group names each one.
COMMANDS_GROUP = "abk.commands"
# What each such command needs installed, for the message when it is not.
COMMAND_PACKAGES = {"worker": "worker"}


def register_missing(sub: Any, name: str, package: str) -> None:
    """Register `name` so it says its package is not installed and exits 2."""
    parser = sub.add_parser(name, help=f"needs the {package} package, which is not installed")
    parser.add_argument("rest", nargs=argparse.REMAINDER)
    parser.set_defaults(
        func=lambda args, inst: not_installed(name, package), needs_installation=False
    )


def not_installed(name: str, package: str) -> int:
    print(f"abk {name}: the {package} package is not installed", file=sys.stderr)
    return 2


def register_entry_point_commands(sub: Any) -> None:
    found = {e.name: e for e in importlib.metadata.entry_points(group=COMMANDS_GROUP)}
    loaded: set[str] = set()
    for entry in sorted(found.values(), key=lambda e: e.name):
        module = entry.module
        try:
            register = entry.load()
        except ModuleNotFoundError as error:
            if not error.name or not (module == error.name or module.startswith(f"{error.name}.")):
                raise
            continue  # a stale or partial install: only this command is missing
        register(sub)
        loaded.add(entry.name)
    for name, package in COMMAND_PACKAGES.items():
        if name not in loaded:
            register_missing(sub, name, package)


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
    register_entry_point_commands(sub)
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
