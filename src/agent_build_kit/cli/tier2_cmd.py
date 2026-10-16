"""`abk tier2`: the tier 2 splits of a repo."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_build_kit import profiles
from agent_build_kit.config import (
    REST_SPLIT,
    Tier2Schedule,
    load,
    locate,
    tier2_schedule,
    tier2_splits,
)
from agent_build_kit.config_text_edit import ConfigTextEditError, set_hold
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.tier2 import selection_unavailable
from agent_build_kit.pipeline.tier2_exclusive import check_splits
from agent_build_kit.pipeline.tier2_holds import (
    HELD_FILE,
    ORIGIN_CONFIGURATION,
    SOURCE_COMMAND,
    SOURCE_GATE,
    declared_splits,
    held_splits,
    hold_text,
    remove_hold,
    write_hold,
)
from agent_build_kit.pipeline.wiring import tier2_work
from agent_build_kit.profiles.base import AppliesTier2Selection
from agent_build_kit.timers import current_user


def _run_in(
    where: Path,
    verify_env: dict[str, str],
    run: Callable[..., subprocess.CompletedProcess],
) -> Callable[..., subprocess.CompletedProcess]:
    """`run` from `where` under the verify env, the way a tier 2 run takes its commands."""
    env = {"env": {**os.environ, **verify_env}} if verify_env else {}

    def run_in(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        return run(argv, **{**kwargs, "cwd": where, **env})

    return run_in


def _check_repo(
    name: str,
    installation: Installation,
    run: Callable[..., subprocess.CompletedProcess],
) -> int:
    repo = installation.repo(name)
    config = installation.config
    splits = tier2_splits(repo, config)
    if not any(split.marker is not None for split in splits):
        print(f"{name}: no split is declared; every tier 2 test is in {REST_SPLIT}")
        return 0
    checkout = installation.checkouts[name]
    script = repo.dev_stack is not None and (checkout / repo.dev_stack.script).is_file()
    marker = repo.tests.tier2_marker
    verify_env = installation.verify_env()
    checks = []
    for where, toolchain, commands in tier2_work(
        checkout, repo.projects, profiles.get(repo.profile), marker
    ):
        why = selection_unavailable(toolchain, dev_stack_script=script, splits=splits)
        if why is not None:
            print(f"{name}: a declared split cannot be applied in {where}: {why}")
            return 1
        # `selection_unavailable` has said the profile applies a marker selector.
        assert isinstance(toolchain, AppliesTier2Selection)
        checks += [
            check_splits(toolchain, command, marker, splits, run=_run_in(where, verify_env, run))
            for command in commands
        ]
    print(f"{name}:")
    for index, split in enumerate(splits):
        counts = [check.listings[index].tests for check in checks if check.listings]
        count = "unknown" if None in counts else sum(len(tests or ()) for tests in counts)
        shown = split.marker or f"{marker}, in none of the splits"
        print(f"  {split.name:<14} {shown}  {count} tests")
    findings = [finding for check in checks for finding in check.findings]
    for finding in findings:
        print(f"  finding: {finding}")
    return 1 if findings else 0


def cmd_tier2_check(
    args: argparse.Namespace,
    installation: Installation | None,
    *,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> int:
    assert installation is not None
    names = [args.repo] if args.repo else list(installation.repos)
    try:
        for name in names:
            installation.repo(name)
    except KeyError as error:
        print(f"abk: {error.args[0]}", file=sys.stderr)
        return 2
    return max(_check_repo(name, installation, run) for name in names)


def _refuse_edit(path: Path, split: str, adding: bool, error: Exception) -> int:
    by_hand = (
        f"add `hold: true` to `{split}` under `tests.e2e_splits` in {path}"
        if adding
        else f"remove the `hold: true` line of `{split}` under `tests.e2e_splits` in {path}"
    )
    print(f"abk: nothing was written. {error}", file=sys.stderr)
    print(f"abk: to do it by hand, {by_hand}", file=sys.stderr)
    return 1


def _editable(path: Path, split: str) -> None:
    """Raise ConfigTextEditError when `split`'s `hold` cannot be edited in `path`, changing
    nothing: the edit is tried on a copy first, so that the state file is not written for a
    configuration that cannot follow it."""
    with tempfile.TemporaryDirectory() as scratch:
        trial = Path(scratch) / path.name
        try:
            shutil.copy2(path, trial)
        except OSError as error:
            raise ConfigTextEditError(f"{path}: cannot edit it as text: {error}") from error
        set_hold(trial, None, split, True)


def _known_split(args: argparse.Namespace, installation: Installation) -> bool:
    names = [split.name for split in declared_splits(installation.config)]
    if args.split in names:
        return True
    print(f"abk: `{args.split}` is not a split; declared: {', '.join(names)}", file=sys.stderr)
    return False


def cmd_tier2_hold(args: argparse.Namespace, installation: Installation | None) -> int:
    assert installation is not None
    if not _known_split(args, installation):
        return 2
    path = locate(args.config)
    prior = next(s.hold for s in declared_splits(installation.config) if s.name == args.split)
    try:
        _editable(path, args.split)
        edit = set_hold(path, None, args.split, True)
    except ConfigTextEditError as error:
        return _refuse_edit(path, args.split, True, error)
    try:
        write_hold(
            installation.state_dir,
            args.split,
            reason=args.reason,
            source=SOURCE_COMMAND,
            by=current_user(),
            now=datetime.now(UTC),
        )
    except OSError as error:
        set_hold(path, None, args.split, prior)
        print(f"abk: nothing was held: the state file cannot be written ({error})", file=sys.stderr)
        return 1
    print(f"{edit.summary or 'configuration unchanged'}; wrote the entry for {args.split}")
    return 0


def cmd_tier2_release(args: argparse.Namespace, installation: Installation | None) -> int:
    assert installation is not None
    if not _known_split(args, installation):
        return 2
    now = datetime.now(UTC)
    state = installation.state_dir
    before = held_splits(declared_splits(installation.config), state, now=now)
    if args.split not in before.held and args.split not in before.overridden:
        print(f"{args.split} is not held; nothing changed")
        return 0
    path = locate(args.config)
    try:
        _editable(path, args.split)
    except ConfigTextEditError as error:
        return _refuse_edit(path, args.split, False, error)
    entry = before.held.get(args.split)
    # A gate's entry is its own to write and end.
    if entry is None or entry.source != SOURCE_GATE:
        try:
            remove_hold(state, args.split)
        except ValueError as error:
            print(f"abk: nothing was released. {error}", file=sys.stderr)
            return 1
    try:
        set_hold(path, None, args.split, None)
    except ConfigTextEditError as error:
        return _refuse_edit(path, args.split, False, error)
    print(f"released {args.split}")
    after = held_splits(declared_splits(load(path)), state, now=now).held.get(args.split)
    if after is not None and ORIGIN_CONFIGURATION in after.origins:
        print(
            f"{args.split} is still held by a `hold: true` in {path} that this command "
            "could not remove; remove the line by hand"
        )
    if after is not None and after.source == SOURCE_GATE:
        print(
            f"{args.split} is still held by an entry of its gate ({hold_text(after)}); "
            "the gate may write it again"
        )
    return 0


def cmd_tier2_status(args: argparse.Namespace, installation: Installation | None) -> int:
    assert installation is not None
    splits = declared_splits(installation.config)
    holds = held_splits(splits, installation.state_dir, now=datetime.now(UTC))
    if holds.unreadable:
        print(f"{HELD_FILE} cannot be read; nothing in it counts")
    for split in splits:
        hold = holds.held.get(split.name)
        if hold is not None:
            print(f"{split.name:<14} held    {hold_text(hold)}")
        elif split.name in holds.overridden:
            print(
                f"{split.name:<14} usable  the configuration releases it (`hold: false`) "
                "although the file holds it; the configuration wins"
            )
        else:
            print(f"{split.name:<14} usable")
    limits = installation.config.global_limits
    running = [
        split.name
        for repo in installation.config.repos.values()
        if tier2_schedule(repo, limits) != Tier2Schedule.OFF
        for split in tier2_splits(repo, installation.config)
    ]
    print(f"schedule: {', '.join(dict.fromkeys(running)) or 'none (off)'}")
    return 0


def held_status_lines(installation: Installation) -> list[str]:
    """One line for each split held now, for `abk status`."""
    holds = held_splits(
        declared_splits(installation.config), installation.state_dir, now=datetime.now(UTC)
    )
    return [f"tier 2 split {name}: held, {hold_text(hold)}" for name, hold in holds.held.items()]


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("tier2", help="a repo's tier 2 splits")
    commands = parser.add_subparsers(dest="tier2_command", required=True)
    check = commands.add_parser("check", help="list each split and report overlaps; runs no test")
    check.add_argument("repo", nargs="?", help="the repo (default: every repo)")
    check.set_defaults(func=cmd_tier2_check)
    hold = commands.add_parser(
        "hold", help="hold a split until `release`, in abk.yaml and the state file"
    )
    hold.add_argument("split", help="the split, or `rest`")
    hold.add_argument("--reason", default="held with `abk tier2 hold`", help="why it is held")
    hold.set_defaults(func=cmd_tier2_hold)
    release = commands.add_parser("release", help="end a hold made with `hold`")
    release.add_argument("split", help="the split, or `rest`")
    release.set_defaults(func=cmd_tier2_release)
    status = commands.add_parser("status", help="each split as usable or held, and the schedule")
    status.set_defaults(func=cmd_tier2_status)
