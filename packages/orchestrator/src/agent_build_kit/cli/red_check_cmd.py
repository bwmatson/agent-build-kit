"""`abk red-check`: the tests step sees the build's red verdict on its worktree first."""

from __future__ import annotations

import argparse
import sys

from agent_build_kit import profiles
from agent_build_kit.cli.install_config import Refused, worktree_root
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.gate import tree_red_problems
from agent_build_kit.pipeline.shell import git
from agent_build_kit.pipeline.unit_store import unit_id_of_branch
from agent_build_kit.profiles.base import stubbed_build
from agent_build_kit.run_support import store_for

REFUSED = 2


def cmd_red_check(args: argparse.Namespace, inst: Installation) -> int:
    """Judge the worktree's tree as the build's red check judges a tests commit.

    Exits 0 when every new and changed test fails for the right reason, 1 with each problem
    printed when not, and 2 when there is nothing to judge: the worktree is not on a unit's
    branch, or changes no test file."""
    try:
        worktree = worktree_root()
        prefix = inst.config.git.branch_prefix
        branch = git(worktree, "rev-parse", "--abbrev-ref", "HEAD", check=False).stdout.strip()
        if not branch.startswith(prefix):
            raise Refused(f"the worktree is on `{branch}`, not on a unit's {prefix}<change>/<n>")
        store = store_for(inst)
        unit_id = unit_id_of_branch(store.all(), branch, prefix)
        try:
            held = store.get(unit_id)
        except KeyError:
            raise Refused(f"no unit {unit_id} in the store") from None
        repo = inst.repo(held.repo)
        profile = profiles.get(repo.profile)
        verdict = tree_red_problems(
            worktree,
            profile=profile,
            projects=repo.projects,
            stubbed=stubbed_build(inst.config.builders, profile),
            log=print,
        )
        if not verdict.judged:
            raise Refused("this worktree changes no test file, so there is nothing to judge")
    except Refused as error:
        print(f"abk red-check: refused: {error}", file=sys.stderr)
        return REFUSED
    if verdict.problems:
        print("\n".join(verdict.problems))
        return 1
    print("abk red-check: every new and changed test fails for the right reason")
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser(
        "red-check", help="judge this unit worktree's new and changed tests as the build will"
    )
    parser.set_defaults(func=cmd_red_check)
