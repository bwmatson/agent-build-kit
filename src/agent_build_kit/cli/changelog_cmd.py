"""`abk changelog check [PATH]`: the changelog's form, for any repo the pipeline builds."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agent_build_kit.changelog_form import changelog_problems
from agent_build_kit.config import RepoConfig
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.shell import git


def _top_and_common(cwd: Path) -> tuple[Path, Path] | None:
    """The checkout `cwd` is in and the repository behind it, the same for a worktree."""
    answered = git(
        cwd,
        "rev-parse",
        "--show-toplevel",
        "--path-format=absolute",
        "--git-common-dir",
        check=False,
    )
    lines = answered.stdout.splitlines()
    if answered.returncode or len(lines) != 2:
        return None
    return Path(lines[0]), Path(lines[1]).parent


def _repo_here(inst: Installation, cwd: Path) -> tuple[RepoConfig, Path] | None:
    """The configured repo `cwd` belongs to, with the root of the checkout it is in."""
    found = _top_and_common(cwd)
    if found is None:
        return None
    top, home = found
    for repo in inst.repos.values():
        if repo.path.expanduser().resolve() == home.resolve():
            return repo, top
    return None


def cmd_changelog_check(args: argparse.Namespace, inst: Installation | None) -> int:
    if args.path:
        shown, path = args.path, Path(args.path)
    else:
        here = _repo_here(inst, Path.cwd()) if inst else None
        if here is None:
            print(
                "abk: no PATH given and the current directory is not in a repo of abk.yaml",
                file=sys.stderr,
            )
            return 2
        repo, top = here
        if repo.changelog is None:
            print("changelog check: off for this repo")
            return 0
        shown, path = repo.changelog, top / repo.changelog
    try:
        text = path.read_text()
    except FileNotFoundError:
        print(f"changelog check: {shown} does not exist yet, nothing to check")
        return 0
    problems = changelog_problems(text, shown)
    for problem in problems:
        print(problem)
    return 1 if problems else 0


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("changelog", help="the changelog convention's checks")
    commands = parser.add_subparsers(dest="changelog_command", required=True)
    check = commands.add_parser("check", help="check a changelog's form")
    check.add_argument("path", nargs="?", default=None, help="default: the repo's setting")
    check.set_defaults(func=cmd_changelog_check, needs_installation="optional")
