"""`abk tier2`: the tier 2 splits of a repo."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent_build_kit import profiles
from agent_build_kit.config import REST_SPLIT, tier2_splits
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.tier2 import selection_unavailable
from agent_build_kit.pipeline.tier2_exclusive import check_splits
from agent_build_kit.pipeline.wiring import tier2_work
from agent_build_kit.profiles.base import AppliesTier2Selection


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


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("tier2", help="a repo's tier 2 splits")
    commands = parser.add_subparsers(dest="tier2_command", required=True)
    check = commands.add_parser("check", help="list each split and report overlaps; runs no test")
    check.add_argument("repo", nargs="?", help="the repo (default: every repo)")
    check.set_defaults(func=cmd_tier2_check)
