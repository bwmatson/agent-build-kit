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

from agent_build_kit import profiles
from agent_build_kit.config import (
    REST_SPLIT,
    Tier2Schedule,
    WorkspaceConfig,
    load,
    locate,
    tier2_schedule,
    tier2_splits,
)
from agent_build_kit.config_text_edit import ConfigTextEditError, TextEdit, set_hold
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.e2e import listing_runner, selection_unavailable
from agent_build_kit.pipeline.e2e_exclusive import check_splits
from agent_build_kit.pipeline.e2e_holds import (
    HELD_FILE,
    ORIGIN_CONFIGURATION,
    SOURCE_COMMAND,
    SOURCE_GATE,
    current_holds,
    declared_splits,
    hold_text,
    remove_hold,
    write_hold,
)
from agent_build_kit.pipeline.wiring import tier2_work
from agent_build_kit.profiles.base import AppliesTier2Selection
from agent_build_kit.timers import current_user


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
    env = {**os.environ, **verify_env} if verify_env else None
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
            check_splits(toolchain, command, marker, splits, run=listing_runner(run, where, env))
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


def _places(config: WorkspaceConfig, split: str) -> list[str | None]:
    """Where `split` is declared: None for the top-level `tests.e2e_splits` (always for `rest`),
    and the name of each repo whose own `tests.e2e_splits` declares it."""
    places: list[str | None] = []
    if split == REST_SPLIT or split in config.tests.tier2_splits:
        places.append(None)
    places += [
        name
        for name, repo in config.repos.items()
        if repo.tests.tier2_splits is not None
        and (split == REST_SPLIT or split in repo.tests.tier2_splits)
    ]
    return places


def _where(place: str | None) -> str:
    return "tests.e2e_splits" if place is None else f"repos.{place}.tests.e2e_splits"


def _refuse_edit(
    path: Path, split: str, places: list[str | None], adding: bool, error: Exception
) -> int:
    action = "add `hold: true` to" if adding else "remove the `hold: true` line of"
    print(f"abk: nothing was written. {error}", file=sys.stderr)
    for place in places:
        print(
            f"abk: to do it by hand, {action} `{split}` under `{_where(place)}` in {path}",
            file=sys.stderr,
        )
    return 1


def _editable(path: Path, split: str, places: list[str | None]) -> None:
    """Raise ConfigTextEditError when `split`'s `hold` cannot be edited at every place in
    `path`, changing nothing: the edits are tried on a copy first, so that the state file is
    not written for a configuration that cannot follow it."""
    with tempfile.TemporaryDirectory() as scratch:
        trial = Path(scratch) / path.name
        try:
            shutil.copy2(path, trial)
        except OSError as error:
            raise ConfigTextEditError(f"{path}: cannot edit it as text: {error}") from error
        for place in places:
            set_hold(trial, place, split, True)


def _edit_all(
    path: Path, split: str, places: list[str | None], value: bool | None
) -> tuple[list[TextEdit], Callable[[], None]]:
    """Set `hold` of `split` at every place; the edits made and a function putting the file
    back as it was, backup included. When an edit refuses, the earlier ones are undone."""
    original = path.read_bytes()
    edits: list[TextEdit] = []

    def undo() -> None:
        path.write_bytes(original)
        for edit in edits:
            if edit.backup is not None:
                edit.backup.unlink(missing_ok=True)

    try:
        for place in places:
            edits.append(set_hold(path, place, split, value))
    except ConfigTextEditError:
        undo()
        raise
    return edits, undo


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
    places = _places(installation.config, args.split)
    try:
        _editable(path, args.split, places)
        edits, undo = _edit_all(path, args.split, places, True)
    except ConfigTextEditError as error:
        return _refuse_edit(path, args.split, places, True, error)
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
        undo()
        print(f"abk: nothing was held: the state file cannot be written ({error})", file=sys.stderr)
        return 1
    for edit in edits:
        print(edit.summary)
    print(f"wrote the entry for {args.split}")
    return 0


def cmd_tier2_release(args: argparse.Namespace, installation: Installation | None) -> int:
    assert installation is not None
    if not _known_split(args, installation):
        return 2
    now = datetime.now(UTC)
    state = installation.state_dir
    before = current_holds(installation.config, state, now=now)
    if args.split not in before.held and args.split not in before.overridden:
        print(f"{args.split} is not held; nothing changed")
        return 0
    path = locate(args.config)
    places = _places(installation.config, args.split)
    try:
        _editable(path, args.split, places)
        edits, undo = _edit_all(path, args.split, places, None)
    except ConfigTextEditError as error:
        return _refuse_edit(path, args.split, places, False, error)
    entry = before.held.get(args.split)
    # A gate's entry is its own to write and end.
    if entry is None or entry.source != SOURCE_GATE:
        try:
            remove_hold(state, args.split)
        except (ValueError, OSError) as error:
            undo()
            print(f"abk: nothing was released. {error}", file=sys.stderr)
            return 1
    for edit in edits:
        if edit.changed:
            print(edit.summary)
    after = current_holds(load(path), state, now=now).held.get(args.split)
    if after is None:
        print(f"released {args.split}")
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
    holds = current_holds(installation.config, installation.state_dir)
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
    holds = current_holds(installation.config, installation.state_dir)
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
