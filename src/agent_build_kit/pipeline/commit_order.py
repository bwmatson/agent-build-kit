"""Does this branch read as tests-then-implementation?

Every unit's branch must be a sequence of tests-then-implementation pairs
(docs/architecture.md). The rule isn't about tidy history: a test
committed alongside the code it covers has never been seen to fail, so nothing
shows it can fail. Committing it first, and running it there, is the evidence.

This module answers the structural half — what the commits contain and in what
order. The behavioural half (the tests in that commit actually fail, and fail
for an accepted reason) belongs to the hook that runs them, because it needs a
worktree and a test run.

**Stubs.** A test importing a function that doesn't exist yet fails to import
rather than failing an assertion, so the tests commit may also add
declarations with no behaviour: signatures whose bodies only raise
`NotImplementedError`, dataclass and model fields, empty classes. Anything
with logic in it is the implementation, and belongs in the next commit —
otherwise "stubs allowed" becomes a hole the whole implementation fits
through.
"""

from __future__ import annotations

import ast
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.shell import git_out

TESTS_PREFIX = "test: "
CODE_PREFIX = "feat: "
# What a per-group commit's body says it holds, before the group's "Done when" sentence.
TESTS_BODY = "Stubs and tests for this task group; they fail until its implementation."
CODE_BODY = "The implementation of this task group, which makes its tests pass."
STUB_BODY_HINT = "only `raise NotImplementedError`"

# A path is a test if any part of it is a tests directory, so this holds for a
# monorepo (svc-a/tests/...) as well as a flat one (tests/...). Fixtures and
# conftest live there too and count the same way.
TEST_DIR_NAMES = {"tests", "test", "testing", "__tests__"}
TEST_FILE_PREFIXES = ("test_",)
TEST_FILE_SUFFIXES = ("_test.py", ".test.ts", ".spec.ts")

# Neither tests nor implementation: a README or a design note may ride along
# with either commit, because forcing a separate branch for a one-line doc fix
# would just push authors to skip the rule.
DOC_SUFFIXES = (".md", ".rst", ".txt")


def classify_paths(
    paths: list[str], is_test: Callable[[str], bool] | None = None
) -> dict[str, str]:
    """Label each path "test", "docs" or "code". `is_test` is the toolchain's own say on
    what a test path is, beside the names every toolchain shares."""
    labels: dict[str, str] = {}
    for path in paths:
        parts = Path(path).parts
        name = Path(path).name
        if (
            any(part in TEST_DIR_NAMES for part in parts)
            or name.startswith(TEST_FILE_PREFIXES)
            or name.endswith(TEST_FILE_SUFFIXES)
            or (is_test is not None and is_test(path))
        ):
            labels[path] = "test"
        elif path.endswith(DOC_SUFFIXES):
            labels[path] = "docs"
        else:
            labels[path] = "code"
    return labels


def stub_violations(path: str, content: str) -> list[str]:
    """Report why `content` is more than a declaration, if it is.

    Python is checked properly, with `ast`. Anything else gets no opinion here
    — the structural rules still apply, but "is this only a stub" is a
    language-specific question and a wrong guess would block real work.
    """
    if not path.endswith(".py"):
        return []

    try:
        tree = ast.parse(content)
    except SyntaxError as error:
        # Can't read it, so can't vouch for it. "Unknown" must not mean
        # "allowed" here any more than it does in the usage guard.
        return [f"{path} could not be parsed ({error.msg})"]

    problems: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue

        body = list(node.body)
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            body = body[1:]  # A docstring is fine.

        is_stub = len(body) == 1 and (
            isinstance(body[0], ast.Pass)
            or (isinstance(body[0], ast.Raise) and _raises_not_implemented(body[0]))
            or (isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant))
        )
        if not is_stub:
            problems.append(f"{path}: {node.name}() has a body — a stub's body is {STUB_BODY_HINT}")

    return problems


def _raises_not_implemented(node: ast.Raise) -> bool:
    exc = node.exc
    if isinstance(exc, ast.Call):
        exc = exc.func
    return isinstance(exc, ast.Name) and exc.id in ("NotImplementedError", "NotImplemented")


def _commits(repo: Path, base: str) -> list[str]:
    out = git_out(repo, "rev-list", "--reverse", f"{base}..HEAD")
    return out.splitlines() if out else []


def _files_in(repo: Path, sha: str) -> list[str]:
    out = git_out(repo, "show", "--name-only", "--pretty=format:", sha)
    return [line for line in out.splitlines() if line]


def _file_at(repo: Path, sha: str, path: str) -> str:
    try:
        return git_out(repo, "show", f"{sha}:{path}")
    except subprocess.CalledProcessError:
        return ""  # Deleted in this commit; nothing to vouch for.


def _subject(repo: Path, sha: str) -> str:
    return git_out(repo, "log", "-1", "--format=%s", sha)


def branch_subjects(repo: Path, base: str) -> list[str]:
    """The subject of each commit the checked-out branch carries beyond `base`, oldest first.
    Read from the subjects, not the hashes, so a restack that rewrote every commit changes
    nothing."""
    out = git_out(repo, "log", "--reverse", "--format=%s", f"{base}..HEAD")
    return out.splitlines() if out else []


class GroupProgress(Frozen):
    """How far a stubbed build's branch has got through the unit's groups."""

    done: int  # groups whose tests and implementation commits are both there
    tests_made: bool  # the next group's tests commit is there, its implementation not


def group_progress(subjects: list[str], titles: Sequence[str]) -> GroupProgress:
    """Walk the groups in the unit's order, each taking a `test:` then a `feat:` commit with
    its title from the front of `subjects` (oldest first). The position in the unit, not the
    title, tells groups apart, so two groups with one title are told apart. A branch that does
    not begin with the first group's tests has made no progress."""
    position = 0
    for done, title in enumerate(titles):
        tests = position < len(subjects) and subjects[position] == f"{TESTS_PREFIX}{title}"
        if not tests:
            return GroupProgress(done=done, tests_made=False)
        position += 1
        if position >= len(subjects) or subjects[position] != f"{CODE_PREFIX}{title}":
            return GroupProgress(done=done, tests_made=True)
        position += 1
    return GroupProgress(done=len(titles), tests_made=False)


def _pair_problems(subjects: list[str]) -> list[str]:
    """What is wrong with how `subjects` (oldest first) pair up: each `test:` commit is
    followed directly by a `feat:` commit with the same title."""
    problems: list[str] = []
    for index, subject in enumerate(subjects):
        if not subject.startswith(TESTS_PREFIX):
            continue
        following = subjects[index + 1] if index + 1 < len(subjects) else None
        if following is not None and following.startswith(TESTS_PREFIX):
            problems.append(
                f"`{following}` directly follows another tests commit — each group's tests "
                "are followed by its own implementation commit"
            )
            continue
        title = subject.removeprefix(TESTS_PREFIX)
        if following != f"{CODE_PREFIX}{title}":
            found = f"`{following}`" if following else "nothing"
            problems.append(
                f"`{subject}` is not directly followed by `{CODE_PREFIX}{title}` (next: {found})"
            )
    return problems


def check_structure(
    repo: Path,
    base: str,
    is_test: Callable[[str], bool] | None = None,
    stubs: Callable[[str, str], list[str]] = stub_violations,
    paired: bool = False,
) -> list[str]:
    """Check a branch's commits read as tests-then-implementation.

    `stubs` is the toolchain's check of a code file's content shipped beside tests, by
    path and content; it defaults to the Python one. `paired` also requires every `test:`
    commit to be followed directly by a `feat:` commit of the same title.

    Returns every problem found, so one run shows the whole list rather than
    one problem per push.
    """
    shas = _commits(repo, base)
    if not shas:
        return [f"no commits between {base} and HEAD"]

    problems: list[str] = []
    kinds: list[str] = []
    stub_problems: dict[int, list[str]] = {}

    for index, sha in enumerate(shas):
        labels = classify_paths(_files_in(repo, sha), is_test)
        has_tests = any(kind == "test" for kind in labels.values())
        code_paths = [path for path, kind in labels.items() if kind == "code"]

        if has_tests and code_paths:
            # Tests plus code in one commit is only allowed when the code is
            # stubs, which is what makes the tests fail honestly rather than
            # fail to import.
            found = [
                problem for path in code_paths for problem in stubs(path, _file_at(repo, sha, path))
            ]
            if found:
                stub_problems[index] = found
            kinds.append("tests")
        elif has_tests:
            kinds.append("tests")
        elif code_paths:
            kinds.append("code")
        else:
            kinds.append("docs")

    substantive = [kind for kind in kinds if kind != "docs"]

    if not substantive:
        return ["the branch changes no tests and no code"]

    # The headline first: a reviewer needs to know *which* rule was broken
    # before the file-by-file detail explaining how.
    first_substantive = next(i for i, kind in enumerate(kinds) if kind != "docs")
    if substantive[0] != "tests" or first_substantive in stub_problems:
        problems.append(
            "the first commit contains implementation — a unit's first commit is its "
            "tests (plus stubs), so that they can be seen to fail"
        )

    for index in sorted(stub_problems):
        problems.extend(stub_problems[index])

    if "code" not in substantive:
        problems.append("the branch has no implementation commit, only tests")

    for first, second in zip(substantive, substantive[1:], strict=False):
        if first == "tests" and second == "tests":
            problems.append(
                "two tests commits in a row — each batch of tests is followed by the "
                "implementation that makes it pass, so the pairs stay reviewable"
            )
            break

    if paired:
        problems.extend(_pair_problems([_subject(repo, sha) for sha in shas]))

    return problems
