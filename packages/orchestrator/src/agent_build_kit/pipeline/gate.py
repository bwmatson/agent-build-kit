"""The gate a unit's branch passes before it is pushed.

This is where the separate checks become one answer. A branch may be pushed
when:

1. its commits read as tests-then-implementation (`commit_order`),
2. linting and formatting pass at each tests commit — type checking is
   deliberately skipped there, since tests routinely reference code that
   doesn't exist yet, unless the build is stubbed, whose stubs make the
   tests type-check,
3. the new tests in each tests commit fail, and fail honestly (`red_check`),
4. and the branch tip is green, which the stack runner checks separately
   because it also gates e2e-test.

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
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from agent_build_kit import profiles
from agent_build_kit.budget import cut_tail
from agent_build_kit.config import ProjectConfig, by_project
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.check_runner import CheckCache, CommandResult, run_at_commit
from agent_build_kit.pipeline.commit_order import (
    check_structure,
    classify_paths,
    commits_without_red_check,
)
from agent_build_kit.pipeline.red_check import Rule
from agent_build_kit.pipeline.shell import git
from agent_build_kit.pipeline.stack_runner import GroupStep
from agent_build_kit.pipeline.wiring import classified_tests, ids_for, tests_in_file
from agent_build_kit.profiles.base import (
    ReportsNothingCollected,
    ToolchainProfile,
    located,
)
from agent_build_kit.redaction import redact_text


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


def _left_in_place(repo: Path, sha: str, files: list[str], prefix: str) -> list[str]:
    """The `files` (relative to the project at `prefix`) the commit `sha` holds: a file it
    deletes, or the old path of a rename, is still part of the commit but is not one the
    runner can be given."""
    if not files:
        return []
    paths = [prefix + file for file in files]
    listing = git(repo, "ls-tree", "-r", "--name-only", "-z", sha, "--", *paths).stdout
    held = set(listing.split("\0"))
    return [file for file, path in zip(files, paths, strict=True) if path in held]


# The cache labels of a red check carry the version of the rule that judges it, so a verdict
# recorded when every passing test was a problem is not reused.
RED_LABEL = "red-v2"
RED_STUBBED_LABEL = "red-stubbed-v2"


def _classified_in(repo: Path, sha: str) -> dict[str, Rule]:
    """The rule of each test the commit adds or changes against its parent (`file::test` from
    the checkout's root); none when they cannot be listed (a root commit has no parent), so its
    files run whole."""
    try:
        return classified_tests(repo, f"{sha}^", sha)
    except (subprocess.CalledProcessError, OSError):
        return {}


class _Selection(Frozen):
    """What one project's red run is given: the files it can run, and each selected test's id
    (from the project's root) beside its `file::test` key from the checkout's root. A file with
    no selected test runs whole."""

    files: list[str]
    picked: dict[str, str]

    @property
    def whole(self) -> list[str]:
        """The files that run whole, none of their tests being selected."""
        chosen = {i.split("::")[0] for i in self.picked}
        return [file for file in self.files if file not in chosen]


def _selection(
    toolchain: ToolchainProfile,
    owned: list[str],
    classified: dict[str, Rule],
    repo: Path,
    prefix: str,
    sha: str,
) -> _Selection:
    """The files of `owned` the red command is given (those the toolchain can run and the commit
    leaves in place) and the tests it selects among them, from the tests `classified` lists. The
    one decision the red command and the rules judging its run are both read from."""
    files = _left_in_place(repo, sha, [f for f in owned if toolchain.runs_path(f)], prefix)
    picked: dict[str, str] = {}
    for key in classified:
        path, name = key.split("::", 1)
        for found in ids_for([(path, name)], repo, repo / prefix, toolchain):
            picked[found] = key
    return _Selection(files=files, picked=picked)


def _rules_of(
    selection: _Selection, classified: dict[str, Rule], repo: Path, sha: str, prefix: str
) -> dict[str, Rule]:
    """How each test the red command selects is judged, keyed `file::test` from the project's
    root: the rule of each touched test, and `WITH_FILE` for each test of a file that runs whole
    because none of its tests is selected."""
    rules = {found: classified[key] for found, key in selection.picked.items()}
    for file in selection.whole:
        for test in tests_in_file(repo, sha, prefix + file):
            rules[f"{file}::{test}"] = Rule.WITH_FILE
    return rules


def _red_command(
    toolchain: ToolchainProfile, selection: _Selection, repo: Path, prefix: str
) -> str | None:
    """The red command for the files of `selection` (the project's test files at the tests
    commit), narrowed to the tests the commit added or changed.

    Only the files the toolchain can run and the commit leaves in place are given to the
    runner (a data file under a test folder is part of the commit but is not runnable; a
    deleted file or the old path of a rename is part of it but is gone); with none, there is
    no command.

    A file with no selected test (a helper edit) stays whole beside the selected ids. With no
    test selected in any file the command is the whole-file run.
    """
    owned = selection.files
    if not owned:
        return None
    ids = list(selection.picked)
    if not ids:
        return toolchain.red_command(owned, project=repo / prefix)
    chosen = {file: [i for i in ids if i.split("::")[0] == file] for file in owned}
    return toolchain.red_command(
        owned, [i for file in owned for i in chosen[file] or [file]], project=repo / prefix
    )


class _Run(Frozen):
    """One project's red run of a tests commit, as judged: whether the toolchain says it
    collected no test, and the problems the toolchain found in it."""

    owner: ProjectConfig | None
    empty: bool
    problems: list[str]


def _run_of(
    toolchain: ToolchainProfile,
    red: CommandResult,
    sha: str,
    owner: ProjectConfig | None,
    stubbed: bool,
    rules: dict[str, Rule],
    log: Callable[[str], None] | None = None,
) -> _Run:
    """The judged red run `red` of the project `owner`, judged by `rules`; the log hears each
    selected test with its rule and outcome. A toolchain with no answer for a run
    that collected nothing never says it did."""
    output = red.stdout + red.stderr
    empty = isinstance(toolchain, ReportsNothingCollected) and toolchain.collected_nothing(
        output, red.exit_code
    )
    # Looked up by name, not by `isinstance`, so a toolchain that forwards unknown names
    # to another still answers.
    describe: Callable[[str, dict[str, Rule]], list[str]] | None = getattr(
        toolchain, "red_rule_lines", None
    )
    if log is not None and rules and describe is not None:
        where = _where(sha, owner)
        for line in describe(output, rules):
            log(redact_text(f"{where}{line}", where="red check log"))
    return _Run(
        owner=owner,
        empty=empty,
        problems=_judged_red(toolchain, red, sha, owner, stubbed, rules),
    )


def _settled(sha: str, runs: list[_Run], log: Callable[[str], None] | None) -> list[str]:
    """The problems of a commit's red runs. A project whose run collected no test adds none
    when another project failed for the right reason (a run with no problems), and each such
    excuse is named in `log`. When no project failed for the right reason every problem
    stands, so a helper-only commit is rejected."""
    failed = [run.owner.path if run.owner else "." for run in runs if not run.problems]
    settled: list[str] = []
    for run in runs:
        if run.problems and run.empty and failed:
            if log is not None:
                project = run.owner.path if run.owner else "."
                log(
                    redact_text(
                        f"{sha[:8]}: {project}: excused, its red run collected no test; "
                        f"{', '.join(failed)} failed for the right reason",
                        where="red check log",
                    )
                )
        else:
            settled.extend(run.problems)
    return settled


def _where(sha: str, owner: ProjectConfig | None) -> str:
    """The label a problem of `sha` carries, naming the project when it is not the root."""
    return f"{sha[:8]}: " + (f"{owner.path}: " if owner and owner.prefix else "")


def _prepare(repo: Path, toolchain: ToolchainProfile, prefix: str, tree: Path) -> None:
    """Let a toolchain with something to link into the throwaway `tree` of `repo` do so; one
    that prepares nothing has no `prepare_worktree`."""
    prepare = getattr(toolchain, "prepare_worktree", None)
    if prepare is not None:
        prepare(repo, tree, project=prefix or ".")


def _prepared(
    repo: Path, toolchain: ToolchainProfile, prefix: str, command: str
) -> Callable[[Path], str]:
    """`command` as a function of the worktree it runs in, which it prepares first."""

    def in_tree(tree: Path) -> str:
        _prepare(repo, toolchain, prefix, tree)
        return command

    return in_tree


def _judged_red(
    toolchain: ToolchainProfile,
    red: CommandResult,
    sha: str,
    owner: ProjectConfig | None,
    stubbed: bool,
    rules: dict[str, Rule],
) -> list[str]:
    """The labelled problems the toolchain finds in one red run of `sha`, judged by `rules`;
    none when it is red for the right reason. The one reading both the push gate and the
    build's red check use."""
    output = red.stdout + red.stderr
    ok, found = (
        toolchain.interpret_red(output, red.exit_code, stubbed=True, rules=rules)
        if stubbed
        else toolchain.interpret_red(output, red.exit_code, rules=rules)
    )
    return [] if ok else [f"{_where(sha, owner)}{problem}" for problem in found]


def _red_log(
    red: CommandResult, sha: str, owner: ProjectConfig | None, toolchain: ToolchainProfile
) -> list[str]:
    """The unit-log lines of one red run: the command (which holds the selection), the exit
    code and each test file the toolchain's runner could not load, with the start of its
    error."""
    where = _where(sha, owner)
    return [
        f"{where}red run: {red.command}",
        f"{where}red run exit code {red.exit_code}",
        *(f"{where}{line}" for line in toolchain.collection_errors(red.stdout + red.stderr)),
    ]


def red_problems(
    repo: Path,
    sha: str,
    *,
    profile: ToolchainProfile,
    projects: list[ProjectConfig] | None = None,
    stubbed: bool = False,
    cache: CheckCache | None = None,
    log: Callable[[str], None] | None = None,
) -> list[str]:
    """Every reason the tests commit `sha` was not seen to fail for the right reason, or an
    empty list: only its red run, judged as `check_branch` judges it. A commit `cache` holds is
    not run again; its results are kept apart from the gate's, which cover more."""
    projects = projects or []
    label = RED_STUBBED_LABEL if stubbed else RED_LABEL
    if cache is not None:
        cached = cache.lookup_entry(repo, sha, mode=label)
        if cached is not None:
            passed, earlier = cached
            if passed:
                return []
            if not earlier:
                return [f"{sha[:8]}: previously failed the red check"]
            # The reasons keep the label of the commit first rejected, which a restack may have
            # rewritten, so the note says so.
            return [redact_text(reason, where="red check reasons") for reason in earlier] + [
                f"{sha[:8]}: this content was rejected before, under the commit each reason "
                "names; the check was not run again"
            ]

    def is_test(path: str) -> bool:
        return profiles.for_path(projects, path, profile).is_test_path(path)

    classified = _classified_in(repo, sha)
    runs: list[_Run] = []
    for owner, owned in by_project(projects, _test_files_in(repo, sha, is_test)):
        toolchain = profiles.for_project(owner, profile)
        prefix = owner.prefix if owner else ""
        selection = _selection(toolchain, owned, classified, repo, prefix, sha)
        command = _red_command(toolchain, selection, repo, prefix)
        if command is None:
            continue
        rules = _rules_of(selection, classified, repo, sha, prefix)

        (red,) = run_at_commit(
            repo, sha, [_prepared(repo, toolchain, prefix, command)], subdir=prefix or "."
        )
        if log is not None:
            for line in _red_log(red, sha, owner, toolchain):
                log(redact_text(line, where="red check log"))
        runs.append(_run_of(toolchain, red, sha, owner, stubbed, rules, log))
    problems = _settled(sha, runs, log)
    if cache is not None:
        cache.record(
            repo,
            sha,
            ok=not problems,
            mode=label,
            reasons=[redact_text(problem, where="red check reasons") for problem in problems],
        )
    return problems


class TreeVerdict(Frozen):
    """The red check of a worktree's tree judged in place: whether it changes any test file
    against `HEAD` (`judged`), and the problems found when it does."""

    judged: bool
    problems: list[str]


def tree_red_problems(
    repo: Path,
    *,
    profile: ToolchainProfile,
    projects: list[ProjectConfig] | None = None,
    stubbed: bool = False,
    log: Callable[[str], None] | None = None,
) -> TreeVerdict:
    """The red check of the working tree of `repo` against `HEAD`, run in `repo` itself."""
    raise NotImplementedError


def check_branch(
    repo: Path,
    base: str,
    *,
    cache: CheckCache | None = None,
    profile: ToolchainProfile | None = None,
    projects: list[ProjectConfig] | None = None,
    stubbed: bool = False,
    groups: Sequence[GroupStep] = (),
    log: Callable[[str], None] | None = None,
) -> list[str]:
    """Every reason this branch may not be pushed, or an empty list.

    The clean and red commands, and how the red run's output is read, are the
    toolchain's: the lint and format at the tests commit with type
    checking skipped, since a test importing what does not exist yet is the
    expected state there, and only the tests the commit added or changed run red (by id; the
    files whole where there is no test to select).
    Each test file is the toolchain's of the project it belongs to (`projects`),
    and each project's commands run in its directory; `profile` is the repo's own,
    for a file no project holds. A commit touching several projects passes when
    every project's checks do, except that a project whose red run collected no test is
    excused, and named in `log`, beside a project that failed for the right reason.

    Whether the build is `stubbed` is the repo's profile's to say, and holds for every
    project. A `stubbed` build also needs its commits paired, runs the clean command with types and
    reads the red run as stubbed; its cached results are kept apart from the other mode's.
    `groups` is the unit's groups in order, each with its build mode, which decides whether its
    commits get a red run; none given, each is `tests_and_code`.
    """
    profile = profile or profiles.get("python-uv")
    projects = projects or []
    mode = "stubbed-v2" if stubbed else "v2"
    # Every commit `commits_without_red_check` returns (a test-only group's tests commit, and the
    # commits of a `no_code` or `refactor` group) is judged with no red run, so its result is kept
    # apart under this cache label, kept as "test-only" so recorded results stay valid.
    only_mode = "test-only" if stubbed else ""
    no_red = commits_without_red_check(repo, base, groups if stubbed else ())

    def is_test(path: str) -> bool:
        return profiles.for_path(projects, path, profile).is_test_path(path)

    def stubs(path: str, content: str) -> list[str]:
        return profiles.for_path(projects, path, profile).stub_violations(path, content)

    problems = check_structure(repo, base, is_test, stubs, paired=stubbed, groups=groups)
    if problems:
        # No point running anything: the shape is wrong, so "which commit is
        # the tests commit" isn't yet a meaningful question.
        return problems

    for sha in _tests_commits(repo, base, is_test):
        commit_mode = only_mode if sha in no_red else mode
        if cache is not None:
            cached = cache.lookup(repo, sha, mode=commit_mode)
            if cached is True:
                continue
            if cached is False:
                problems.append(f"{sha[:8]}: previously failed the clean/red checks")
                continue

        files = _test_files_in(repo, sha, is_test)
        if not files:
            continue

        commit_problems: list[str] = []
        classified = {} if sha in no_red else _classified_in(repo, sha)
        runs: list[_Run] = []
        for owner, owned in by_project(projects, files):
            toolchain = profiles.for_project(owner, profile)
            prefix = owner.prefix if owner else ""
            selection = _selection(toolchain, owned, classified, repo, prefix, sha)
            rules = {} if sha in no_red else _rules_of(selection, classified, repo, sha, prefix)
            where = _where(sha, owner)
            clean_line = (
                toolchain.clean_command(types=True) if stubbed else toolchain.clean_command()
            )

            def clean_in(
                tree: Path,
                line: str = clean_line,
                folder: str = prefix,
                profile: ToolchainProfile = toolchain,
            ) -> str:
                # Looked up in the tree at `sha`, which is where the command runs. The tree is
                # prepared here, first, for the red command that follows in the same tree.
                _prepare(repo, profile, folder, tree)
                return located(profile, ["sh", "-c", line], tree / folder, tree)[-1]

            commands: list[str | Callable[[Path], str]] = [clean_in]
            red_line = None if sha in no_red else _red_command(toolchain, selection, repo, prefix)
            if red_line is not None:
                commands.append(red_line)
            clean, *red_run = run_at_commit(repo, sha, commands, subdir=prefix or ".")
            if not clean.ok:
                commit_problems.append(
                    f"{where}lint/format did not pass at the tests commit\n"
                    f"{cut_tail(clean.stdout, 2000)}"
                )
            runs.extend(_run_of(toolchain, red, sha, owner, stubbed, rules, log) for red in red_run)
        commit_problems.extend(_settled(sha, runs, log))

        if cache is not None:
            cache.record(repo, sha, ok=not commit_problems, mode=commit_mode)
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
