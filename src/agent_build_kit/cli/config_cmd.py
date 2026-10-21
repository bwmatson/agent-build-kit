"""`abk config`: which abk.yaml is in force, and what it says once every
default is filled in."""

from __future__ import annotations

import argparse
import difflib
import sys

import yaml

from agent_build_kit.config import (
    ConfigError,
    deprecation_notice,
    deprecations,
    locate,
    models_notices,
    old_setting_notices,
    overlay_path,
    read_overlay,
)
from agent_build_kit.config_migrate import ConfigMigrateError, migrate
from agent_build_kit.init.runtime_choice import confirmed
from agent_build_kit.installation import Installation, load_installation
from agent_build_kit.runtimes.policy_apply import backup_and_replace


def cmd_migrate(args: argparse.Namespace) -> int:
    """Move the abk.yaml in force to the new limits blocks and rename its old test-kind setting
    keys, by text, without loading it: exit 0 when it wrote, was a dry run or had nothing to
    change, 1 when not confirmed, 2 when refused."""
    try:
        path = locate(args.config)
    except ConfigError as error:
        print(f"abk: {error}", file=sys.stderr)
        return 2
    try:
        before = path.read_bytes().decode()
        migrated = migrate(before)
    except (ConfigMigrateError, OSError, UnicodeDecodeError) as error:
        print(f"abk: {path}: {error}", file=sys.stderr)
        return 2
    if migrated.text == before:
        print(f"{path}: nothing needed migrating")
        return 0
    print(
        "".join(
            difflib.unified_diff(
                before.splitlines(keepends=True),
                migrated.text.splitlines(keepends=True),
                fromfile=str(path),
                tofile=str(path),
            )
        ),
        end="",
    )
    if args.dry_run:
        return 0
    if not (args.yes or (sys.stdin.isatty() and confirmed(f"migrate {path}? [y/N] "))):
        print("not migrated; nothing was written")
        return 1
    try:
        backup = backup_and_replace(path, migrated.text)
    except OSError as error:
        print(f"abk: {path}: {error}", file=sys.stderr)
        return 2
    if backup:
        print(f"backed up the original to {backup}")
    print(f"migrated {path}")
    return 0


def cmd_config(args: argparse.Namespace, inst: Installation | None) -> int:
    if args.migrate:
        return cmd_migrate(args)
    if args.yes or args.dry_run:
        print("abk: --yes and --dry-run need --migrate", file=sys.stderr)
        return 2
    if args.path:
        try:
            path = locate(args.config)
        except ConfigError as error:
            print(f"abk: {error}", file=sys.stderr)
            return 2
        print(path)
        if overlay_path(path).is_file():
            print(overlay_path(path))
        return 0
    if inst is None:
        try:
            inst = load_installation(args.config)
        except ConfigError as error:
            print(f"abk: {error}", file=sys.stderr)
            return 2
    path = locate(args.config)
    for key in deprecations(path):
        print(deprecation_notice(key), file=sys.stderr)
    for old in old_setting_notices(path):
        print(old, file=sys.stderr)
    for notice in models_notices(path):
        print(notice, file=sys.stderr)
    local = read_overlay(path)
    if local:
        print(f"{overlay_path(path)} set: {', '.join(local)}", file=sys.stderr)
    data = inst.config.model_dump(by_alias=True, mode="json")
    print(yaml.safe_dump(data, sort_keys=False, default_flow_style=False), end="")
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("config", help="show the effective workspace config, or its path")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--show", action="store_true", help="the effective config with defaults filled (default)"
    )
    mode.add_argument(
        "--path",
        action="store_true",
        help="the abk.yaml in force, and the overlay when there is one",
    )
    mode.add_argument(
        "--migrate",
        action="store_true",
        help="move the abk.yaml in force to global_limits and project_limits, by text",
    )
    parser.add_argument("--yes", action="store_true", help="with --migrate: do not ask")
    parser.add_argument(
        "--dry-run", action="store_true", help="with --migrate: print the diff, write nothing"
    )
    # `--path` has to answer for a file that will not load.
    parser.set_defaults(func=cmd_config, needs_installation="optional")
