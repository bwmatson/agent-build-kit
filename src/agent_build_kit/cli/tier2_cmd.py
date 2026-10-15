"""`abk tier2`: the tier 2 splits of a repo."""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Callable

from agent_build_kit import profiles
from agent_build_kit.config import REST_SPLIT, tier2_splits
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.tier2 import selection_unavailable
from agent_build_kit.pipeline.tier2_exclusive import check_splits
from agent_build_kit.profiles.base import AppliesTier2Selection


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
    toolchain = profiles.get(repo.profile)
    checkout = installation.checkouts[name]
    script = repo.dev_stack is not None and (checkout / repo.dev_stack.script).is_file()
    why = selection_unavailable(toolchain, dev_stack_script=script, splits=splits)
    if why is not None:
        print(f"{name}: a declared split cannot be applied: {why}")
        return 1
    marker = repo.tests.tier2_marker
    # `selection_unavailable` has said the profile applies a marker selector.
    assert isinstance(toolchain, AppliesTier2Selection)
    checks = [
        check_splits(toolchain, command, marker, splits, run=run)
        for command in toolchain.tier2_commands(checkout, marker=marker)
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
    known = list(installation.repos)
    if args.repo is not None and args.repo not in known:
        print(f"abk: unknown repo {args.repo!r} (known: {', '.join(known)})", file=sys.stderr)
        return 2
    names = [args.repo] if args.repo else known
    return max(_check_repo(name, installation, run) for name in names)


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("tier2", help="a repo's tier 2 splits")
    commands = parser.add_subparsers(dest="tier2_command", required=True)
    check = commands.add_parser("check", help="list each split and report overlaps; runs no test")
    check.add_argument("repo", nargs="?", help="the repo (default: every repo)")
    check.set_defaults(func=cmd_tier2_check)
