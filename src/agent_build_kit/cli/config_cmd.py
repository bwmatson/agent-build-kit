"""`abk config`: which abk.yaml is in force, and what it says once every
default is filled in."""

from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path

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
    runtime_for,
    workspace_full_ceiling,
)
from agent_build_kit.config_migrate import ConfigMigrateError, migrate
from agent_build_kit.config_migrate_machine import MachineRequest
from agent_build_kit.config_migrate_write import (
    ignore_diff,
    in_repository,
    running_units_notice,
    uncommitted_hint,
    write_both,
)
from agent_build_kit.init.runtime_choice import confirmed
from agent_build_kit.installation import Installation, load_installation
from agent_build_kit.pipeline.shell import git, is_tracked
from agent_build_kit.runtimes.policy_apply import backup_and_replace


def _diff(before: str, after: str, path: Path, *, new: bool = False) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"{path} (new file)" if new else str(path),
            tofile=str(path),
        )
    )


def _machine_request(
    path: Path, include_defaults: bool
) -> tuple[MachineRequest, str | None] | None:
    """What the machine move needs for a git-tracked abk.yaml, with the local file's text; None
    when the abk.yaml is outside a git repository or git does not track it."""
    if not in_repository(path.parent) or not is_tracked(path.parent, path.name):
        return None
    toplevel = Path(git(path.parent, "rev-parse", "--show-toplevel").stdout.strip())
    local = overlay_path(path)
    local_text = local.read_bytes().decode() if local.exists() else None
    request = MachineRequest(
        toplevel=toplevel, local_text=local_text, include_defaults=include_defaults
    )
    return request, local_text


def cmd_migrate(args: argparse.Namespace) -> int:
    """Move the abk.yaml in force to the new limits blocks, rename its old test-kind setting keys,
    move a flat `models:` block under the runtime in force's `runtimes.<name>.models` and, for a
    git-tracked abk.yaml, its machine settings to abk.local.yaml, by text, without loading it:
    exit 0 when it wrote, was a dry run or had nothing to change, 1 when not confirmed, 2 when
    refused."""
    try:
        path = locate(args.config)
    except ConfigError as error:
        print(f"abk: {error}", file=sys.stderr)
        return 2
    local = overlay_path(path)
    try:
        before = path.read_bytes().decode()
        wanted = _machine_request(path, args.include_defaults)
        machine, local_before = wanted if wanted else (None, None)
        migrated = migrate(before, runtime_for(path), machine)
        local_after = migrated.local_text
        ignore = ignore_diff(path.parent) if local_after != local_before else ""
    except (ConfigMigrateError, OSError, UnicodeDecodeError) as error:
        print(f"abk: {path}: {error}", file=sys.stderr)
        return 2
    for conflict in migrated.conflicts:
        key, stopped = ".".join(conflict.path), ".".join(conflict.local_path)
        print(f"left {key} in abk.yaml: abk.local.yaml already sets {stopped}; keep one of them")
    both = local_after is not None and local_after != local_before
    if migrated.text == before and not both:
        print(f"{path}: nothing needed migrating")
        return 0
    print(ignore, end="")
    print(_diff(before, migrated.text, path), end="")
    if both and local_after is not None:
        print(_diff(local_before or "", local_after, local, new=local_before is None), end="")
    hint = uncommitted_hint(path) if machine else None
    if hint:
        print(hint, file=sys.stderr)
    if args.dry_run:
        return 0
    notice = running_units_notice(path) if machine else None
    if notice:
        print(notice, file=sys.stderr)
    names = f"{path} and {local}" if both else str(path)
    if not (args.yes or (sys.stdin.isatty() and confirmed(f"migrate {names}? [y/N] "))):
        print("not migrated; nothing was written")
        return 1
    try:
        if both and local_after is not None:
            write_both(path, migrated.text, local_after, show_ignore_diff=False)
            backup = None
        else:
            backup = backup_and_replace(path, migrated.text)
    except (ConfigMigrateError, OSError) as error:
        print(f"abk: {path}: {error}", file=sys.stderr)
        return 2
    if backup:
        print(f"backed up the original to {backup}")
    print(f"migrated {names}")
    if hint:
        print(hint, file=sys.stderr)
    return 0


def cmd_config(args: argparse.Namespace, inst: Installation | None) -> int:
    if args.migrate:
        return cmd_migrate(args)
    if args.yes or args.dry_run:
        print("abk: --yes and --dry-run need --migrate", file=sys.stderr)
        return 2
    if args.include_defaults:
        print("abk: --include-defaults needs --migrate", file=sys.stderr)
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
        print(notice.text, file=sys.stderr)
    local = read_overlay(path)
    if local:
        print(f"{overlay_path(path)} set: {', '.join(local)}", file=sys.stderr)
    data = inst.config.model_dump(by_alias=True, mode="json")
    data["review"]["ceilings"]["full"] = workspace_full_ceiling(inst.config)
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
        help="move the abk.yaml in force to global_limits and project_limits, and a flat models: "
        "block under runtimes.<name>.models, and, when git tracks it, its machine settings to "
        "abk.local.yaml, by text",
    )
    parser.add_argument("--yes", action="store_true", help="with --migrate: do not ask")
    parser.add_argument(
        "--dry-run", action="store_true", help="with --migrate: print the diff, write nothing"
    )
    parser.add_argument(
        "--include-defaults",
        action="store_true",
        help="with --migrate: also move the settings a team may commit (limits, e2e_schedule off, "
        "split hold) to abk.local.yaml",
    )
    # `--path` has to answer for a file that will not load.
    parser.set_defaults(func=cmd_config, needs_installation="optional")
