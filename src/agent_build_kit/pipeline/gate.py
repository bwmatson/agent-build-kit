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
from pathlib import Path

from agent_build_kit import profiles
from agent_build_kit.pipeline.check_runner import CheckCache, run_at_commit
from agent_build_kit.pipeline.commit_order import check_structure, classify_paths
from agent_build_kit.profiles.base import ToolchainProfile


def _tests_commits(repo: Path, base: str) -> list[str]:
    """The commits on this branch that are tests-only (plus stubs)."""
    import subprocess

    out = subprocess.run(
        ["git", "rev-list", "--reverse", f"{base}..HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()

    tests_commits = []
    for sha in out:
        files = subprocess.run(
            ["git", "show", "--name-only", "--pretty=format:", sha],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
        labels = classify_paths(files)
        if any(kind == "test" for kind in labels.values()):
            tests_commits.append(sha)
    return tests_commits


def _test_files_in(repo: Path, sha: str) -> list[str]:
    import subprocess

    files = subprocess.run(
        ["git", "show", "--name-only", "--pretty=format:", sha],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return [path for path, kind in classify_paths(files).items() if kind == "test"]


def check_branch(
    repo: Path,
    base: str,
    *,
    cache: CheckCache | None = None,
    profile: ToolchainProfile | None = None,
) -> list[str]:
    """Every reason this branch may not be pushed, or an empty list.

    The clean and red commands, and how the red run's output is read, are the
    toolchain's (`profile`): the lint and format at the tests commit with type
    checking skipped, since a test importing what does not exist yet is the
    expected state there, and only the test files the commit touched run red.
    """
    profile = profile or profiles.get("python-uv")
    problems = check_structure(repo, base)
    if problems:
        # No point running anything: the shape is wrong, so "which commit is
        # the tests commit" isn't yet a meaningful question.
        return problems

    for sha in _tests_commits(repo, base):
        if cache is not None:
            cached = cache.lookup(repo, sha)
            if cached is True:
                continue
            if cached is False:
                problems.append(f"{sha[:8]}: previously failed the clean/red checks")
                continue

        files = _test_files_in(repo, sha)
        if not files:
            continue

        clean, red = run_at_commit(
            repo,
            sha,
            [profile.clean_command(), profile.red_command(files)],
        )

        commit_problems: list[str] = []
        if not clean.ok:
            commit_problems.append(
                f"{sha[:8]}: lint/format did not pass at the tests commit\n{clean.stdout[-2000:]}"
            )

        ok, red_problems = profile.interpret_red(red.stdout + red.stderr, red.exit_code)
        if not ok:
            commit_problems.extend(f"{sha[:8]}: {problem}" for problem in red_problems)

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
