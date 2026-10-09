"""`abk pr view` and `abk pr diff`: what an agent may read of its local pull request.

Both only read: the pull requests of a repo whose forge is `local` live in the state directory,
and nothing here writes there or touches the repo.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agent_build_kit.forges.base import RepoId
from agent_build_kit.forges.local import LocalForge
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.shell import git


def _repo_name(args: argparse.Namespace, inst: Installation) -> str | None:
    """The repo asked for, else the one whose checkout holds the working directory."""
    if args.repo:
        return args.repo
    here = _common_dir(Path.cwd())
    if here is None:
        return None
    # Through git, so a worktree of a checkout, wherever it sits, finds that checkout.
    return next((n for n, path in inst.checkouts.items() if _common_dir(path) == here), None)


def _common_dir(path: Path) -> Path | None:
    if not path.is_dir():
        return None
    found = git(path, "rev-parse", "--path-format=absolute", "--git-common-dir", check=False)
    return None if found.returncode else Path(found.stdout.strip()).resolve()


def _number(forge: LocalForge, repo: RepoId, args: argparse.Namespace) -> int | None:
    """The number asked for, else the open pull request of the branch checked out here."""
    if args.number is not None:
        return args.number
    branch = git(Path.cwd(), "symbolic-ref", "--short", "-q", "HEAD", check=False).stdout.strip()
    return forge.find_pr(repo, head=branch) if branch else None


def _find(args: argparse.Namespace, inst: Installation) -> tuple[LocalForge, RepoId, int] | None:
    name = _repo_name(args, inst)
    if name is None or name not in inst.repos or inst.repo(name).forge != "local":
        print("abk pr: name a repo whose forge is local with --repo", file=sys.stderr)
        return None
    forge = LocalForge(inst.state_dir)
    repo = forge.identity(inst.repo(name))
    number = _number(forge, repo, args)
    if number is None or forge.record(repo, number) is None:
        print(
            f"abk pr: no local pull request {number or 'for this branch'} in {name}",
            file=sys.stderr,
        )
        return None
    return forge, repo, number


def cmd_view(args: argparse.Namespace, inst: Installation) -> int:
    found = _find(args, inst)
    if found is None:
        return 1
    forge, repo, number = found
    pull = forge.record(repo, number) or {}
    print(f"#{number} {pull['title']}")
    print(f"state: {forge.state_of(repo, number) or pull['state']}")
    print(f"head: {pull['head']}")
    print(f"base: {pull['base']}")
    print()
    print(pull["body"])
    return 0


def cmd_diff(args: argparse.Namespace, inst: Installation) -> int:
    found = _find(args, inst)
    if found is None:
        return 1
    forge, repo, number = found
    shown = forge.diff(repo, number)
    if shown is None:
        print(f"abk pr: the branch of #{number} is not in the checkout", file=sys.stderr)
        return 1
    print(shown, end="")
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("pr", help="read a local pull request (view, diff)")
    actions = parser.add_subparsers(dest="action", required=True)
    for name, func, text in (
        ("view", cmd_view, "print the pull request"),
        ("diff", cmd_diff, "print the branch's diff over its base"),
    ):
        action = actions.add_parser(name, help=text)
        action.add_argument(
            "number",
            nargs="?",
            type=int,
            help="default: the pull request of the checked-out branch",
        )
        action.add_argument(
            "--repo", default="", help="default: the repo holding the working directory"
        )
        action.set_defaults(func=func)
