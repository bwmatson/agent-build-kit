"""The gate a unit's branch passes before it is pushed.

This is where the separate checks become one answer. A branch may be pushed
when:

1. its commits read as tests-then-implementation (`commit_order`),
2. linting and formatting pass at each tests commit — type checking is
   deliberately skipped there, since tests routinely reference code that
   doesn't exist yet,
3. the new tests in each tests commit fail, and fail honestly (`red_check`),
4. and the branch tip is green, which the stack runner checks separately
   because it also gates tier 2.

Steps 2 and 3 run in a throwaway worktree at the tests commit
(`check_runner`), and their results are cached by patch-id so a restack
doesn't re-run work already verified.

Intended to be invoked from a Claude Code `PreToolUse` hook on pushes and on
`gh pr create` (docs/architecture.md). It prints what is wrong and
exits non-zero; it never fixes anything itself, because a gate that edits the
work it is judging is no longer a gate.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

from agent_build_kit import profiles
from agent_build_kit.budget import cut_tail
from agent_build_kit.config import ProjectConfig, by_project
from agent_build_kit.pipeline.check_runner import CheckCache, run_at_commit
from agent_build_kit.pipeline.commit_order import check_structure, classify_paths
from agent_build_kit.pipeline.shell import git
from agent_build_kit.profiles.base import ToolchainProfile


def _files_of(repo: Path, sha: str) -> list[str]:
    return git(repo, "show", "--name-only", "--pretty=format:", sha).stdout.split()


def _tests_commits(repo: Path, base: str, is_test: Callable[[str], bool]) -> list[str]:
    """The commits on this branch that are tests-only (plus stubs)."""
    out = git(repo, "rev-list", "--reverse", f"{base}..HEAD").stdout.split()

    tests_commits = []
    for sha in out:
        if _test_files_in(repo, sha, is_test):
            tests_commits.append(sha)
    return tests_commits


def _test_files_in(repo: Path, sha: str, is_test: Callable[[str], bool]) -> list[str]:
    files = _files_of(repo, sha)
    return [path for path, kind in classify_paths(files, is_test).items() if kind == "test"]


def check_branch(
    repo: Path,
    base: str,
    *,
    cache: CheckCache | None = None,
    profile: ToolchainProfile | None = None,
    projects: list[ProjectConfig] | None = None,
) -> list[str]:
    """Every reason this branch may not be pushed, or an empty list.

    The clean and red commands, and how the red run's output is read, are the
    toolchain's: the lint and format at the tests commit with type
    checking skipped, since a test importing what does not exist yet is the
    expected state there, and only the test files the commit touched run red.
    Each test file is the toolchain's of the project it belongs to (`projects`),
    and each project's commands run in its directory; `profile` is the repo's own,
    for a file no project holds. A commit touching several projects passes when
    every project's checks do.
    """
    profile = profile or profiles.get("python-uv")
    projects = projects or []

    def is_test(path: str) -> bool:
        return profiles.for_path(projects, path, profile).is_test_path(path)

    def stubs(path: str, content: str) -> list[str]:
        return profiles.for_path(projects, path, profile).stub_violations(path, content)

    problems = check_structure(repo, base, is_test, stubs)
    if problems:
        # No point running anything: the shape is wrong, so "which commit is
        # the tests commit" isn't yet a meaningful question.
        return problems

    for sha in _tests_commits(repo, base, is_test):
        if cache is not None:
            cached = cache.lookup(repo, sha)
            if cached is True:
                continue
            if cached is False:
                problems.append(f"{sha[:8]}: previously failed the clean/red checks")
                continue

        files = _test_files_in(repo, sha, is_test)
        if not files:
            continue

        commit_problems: list[str] = []
        for owner, owned in by_project(projects, files):
            toolchain = profiles.for_project(owner, profile)
            prefix = owner.prefix if owner else ""
            where = f"{sha[:8]}: " + (f"{owner.path}: " if prefix and owner else "")
            clean, red = run_at_commit(
                repo,
                sha,
                [
                    toolchain.clean_command(),
                    toolchain.red_command(owned),
                ],
                subdir=prefix or ".",
            )
            if not clean.ok:
                commit_problems.append(
                    f"{where}lint/format did not pass at the tests commit\n"
                    f"{cut_tail(clean.stdout, 2000)}"
                )
            ok, red_problems = toolchain.interpret_red(red.stdout + red.stderr, red.exit_code)
            if not ok:
                commit_problems.extend(f"{where}{problem}" for problem in red_problems)

        if cache is not None:
            cache.record(repo, sha, ok=not commit_problems)
        problems.extend(commit_problems)

    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gate a unit's branch before it is pushed.")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--base", default="main", help="branch this unit stacks on")
    parser.add_argument("--cache", type=Path, default=None)
    parser.add_argument("--profile", default="python-uv", help="toolchain profile of the repo")
    args = parser.parse_args(argv)

    cache = CheckCache(args.cache) if args.cache else None
    problems = check_branch(args.repo, args.base, cache=cache, profile=profiles.get(args.profile))

    for problem in problems:
        print(f"✗ {problem}", file=sys.stderr)

    if problems:
        print(f"\n{len(problems)} problem(s): this branch is not ready to push", file=sys.stderr)
        return 1

    print("✓ tests-first: commits ordered, clean at the tests commit, and red there")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
