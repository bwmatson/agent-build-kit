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
from typing import TYPE_CHECKING

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.group_mode import GroupMode, mode_at
from agent_build_kit.pipeline.shell import git, git_out

if TYPE_CHECKING:
    from agent_build_kit.pipeline.stack_runner import GroupStep

TESTS_PREFIX = "test: "
CODE_PREFIX = "feat: "
FIX_PREFIX = "fix: "
ALREADY_BUILT_TRAILER = "Already-built"  # the trailer key; its one value is `yes`
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

# Configuration a group may change without writing code.
CONFIG_SUFFIXES = (".yml", ".yaml", ".toml", ".json", ".ini", ".cfg")


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


def recorded_built(repo: Path, sha: str) -> bool:
    """Whether the commit is marked `Already-built: yes` and holds no file. A file keeps the
    marker from excusing real work."""
    marked = git_out(
        repo, "log", "-1", f"--format=%(trailers:key={ALREADY_BUILT_TRAILER},valueonly)", sha
    )
    return marked.strip() == "yes" and not _files_in(repo, sha)


def branch_commit_subjects(repo: Path, base: str, ref: str = "HEAD") -> list[tuple[str, str]]:
    """The hash and subject of each commit the branch at `ref` carries beyond `base`, oldest
    first."""
    out = git_out(repo, "log", "--reverse", "--format=%H%x00%s", f"{base}..{ref}")
    return [tuple(line.split("\0", 1)) for line in out.splitlines()]  # pyrefly: ignore[bad-return]


def branch_subjects(repo: Path, base: str) -> list[str]:
    """The subject of each commit the checked-out branch carries beyond `base`, oldest first.
    Read from the subjects, not the hashes, so a restack that rewrote every commit changes
    nothing."""
    return [subject for _, subject in branch_commit_subjects(repo, base)]


class GroupProgress(Frozen):
    """How far a stubbed build's branch has got through the unit's groups."""

    done: int  # groups done: each has its pair, or for a test-only group its tests commit
    tests_made: bool  # the next group's tests commit is there, its implementation not
    lone_feat: str = ""  # the `feat:` subject of the next group found where its `test:` belongs


def _group_size(subjects: list[str], position: int, title: str, mode: GroupMode) -> int | None:
    """How many commits a finished group takes from `subjects` at `position`, None when the
    group is not finished there. A `tests_and_code` group takes a `test:` then a `feat:`; a
    `tests_only` group its `test:` alone; a `no_code` group a lone `feat:` or that pair; a
    `refactor` group a lone `feat:`."""
    tests, feat = f"{TESTS_PREFIX}{title}", f"{CODE_PREFIX}{title}"
    at = subjects[position] if position < len(subjects) else None
    following = subjects[position + 1] if position + 1 < len(subjects) else None
    if mode.accepts_tests_commit and at == tests:
        if mode is GroupMode.TESTS_ONLY:
            return 1
        return 2 if following == feat else None
    if mode in (GroupMode.NO_CODE, GroupMode.REFACTOR) and at == feat:
        return 1
    return None


def group_progress(
    subjects: list[str], titles: Sequence[str], modes: Sequence[GroupMode] = ()
) -> GroupProgress:
    """Walk the groups in the unit's order, each taking the commits its mode calls for with its
    title from the front of `subjects` (oldest first); `modes` is by position, like `titles`, and
    a group with none is `tests_and_code` (a bool is the earlier `test_only` flag). The position
    in the unit, not the title, tells groups apart, so two groups with one title are told apart.
    A branch that does not begin with the first group's commits has made no progress."""
    position = 0
    for done, title in enumerate(titles):
        mode = mode_at(modes, done)
        size = _group_size(subjects, position, title, mode)
        if size is None:
            at = subjects[position] if position < len(subjects) else ""
            if mode.accepts_tests_commit and mode.writes_code and at == f"{TESTS_PREFIX}{title}":
                return GroupProgress(done=done, tests_made=True)
            lone = mode is GroupMode.TESTS_AND_CODE and at == f"{CODE_PREFIX}{title}"
            return GroupProgress(done=done, tests_made=False, lone_feat=at if lone else "")
        position += size
    return GroupProgress(done=len(titles), tests_made=False)


def adopted_subject(unit_title: str, steps: Sequence[GroupStep], subjects: list[str]) -> str:
    """The subject of the commit a person's adopted changes become, so the counter takes it for the
    commit the build expected next: `test:` or `feat:` with the title of the group `subjects`
    (oldest first) has reached, `fix: <last title> (adopted)` once every group has its commits.
    `steps` is empty for a unit that is not built in stubbed groups, which takes `unit_title`."""
    if not steps:
        return f"{FIX_PREFIX}{unit_title} (adopted)" if subjects else f"{CODE_PREFIX}{unit_title}"
    progress = group_progress(
        subjects, [step.title for step in steps], [step.mode for step in steps]
    )
    if progress.done >= len(steps):
        return f"{FIX_PREFIX}{steps[-1].title} (adopted)"
    reached = steps[progress.done]
    prefix = CODE_PREFIX if progress.tests_made or not reached.mode.writes_tests else TESTS_PREFIX
    return f"{prefix}{reached.title}"


def superseded_pairs(
    repo: Path, ref: str, base: str, titles: Sequence[str], modes: Sequence[GroupMode]
) -> list[list[str]] | None:
    """The commits of each group on the branch at `ref`, oldest group first, when the branch
    beyond `base` is exactly the commits each of the groups (`titles`, by position, with `modes`)
    takes, in order; None for any other branch, which has a commit that belongs to no group or
    lacks one."""
    found = branch_commit_subjects(repo, base, ref)
    shas = [sha for sha, _ in found]
    subjects = [subject for _, subject in found]
    taken = 0
    groups: list[list[str]] = []
    for index, title in enumerate(titles):
        size = _group_size(subjects, taken, title, mode_at(modes, index))
        if size is None:
            return None
        groups.append(shas[taken : taken + size])
        taken += size
    return groups if taken == len(shas) else None


def cherry_pick(repo: Path, shas: Sequence[str], *, unit_id: str = "") -> bool:
    """Pick `shas` onto the checked-out branch in order, an originally empty commit (a group
    recorded as already built) included; False, with the branch as it was before the first
    pick and a clean tree, at the first that does not apply, so a group's commits come whole or
    not at all. With `unit_id`, each picked commit's `Unit:` trailer names that unit."""
    start = git_out(repo, "rev-parse", "HEAD")
    for sha in shas:
        if git(repo, "cherry-pick", "--allow-empty", sha, check=False).returncode:
            git(repo, "cherry-pick", "--abort", check=False)
            git(repo, "reset", "-q", "--hard", start)
            return False
        if unit_id and not _name_unit(repo, unit_id):
            git(repo, "reset", "-q", "--hard", start)
            return False
    return True


def _name_unit(repo: Path, unit_id: str) -> bool:
    """Rewrite the `Unit:` trailer of HEAD to `unit_id`, keeping the rest of its message. The
    commit already passed the gate, so no hook runs; False when the rewrite fails."""
    message = git_out(repo, "log", "-1", "--format=%B")
    old_lines = message.split("\n")
    lines = [f"Unit: {unit_id}" if row.startswith("Unit: ") else row for row in old_lines]
    if lines == old_lines:
        return True
    amended = git(
        repo,
        "commit",
        "-q",
        "--amend",
        "--no-verify",
        "--allow-empty",
        "-m",
        "\n".join(lines),
        check=False,
    )
    return amended.returncode == 0


def _commit_modes(subjects: list[str], groups: Sequence[GroupStep]) -> list[GroupMode | None]:
    """For each subject, the mode of the group whose commit it is, None for a commit that belongs
    to no group. The groups are walked in order, each taking the commits its mode calls for with
    its title, so position tells two groups with one title apart."""
    found: list[GroupMode | None] = [None] * len(subjects)
    position = 0
    for group in groups:
        size = _group_size(subjects, position, group.title, group.mode)
        if size is None:
            if position < len(subjects) and subjects[position] == f"{TESTS_PREFIX}{group.title}":
                found[position] = group.mode if group.mode.accepts_tests_commit else None
            break
        found[position : position + size] = [group.mode] * size
        position += size
    return found


def commits_of_test_only_groups(repo: Path, base: str, groups: Sequence[GroupStep]) -> set[str]:
    """The commits of the branch that are the tests commit of a test-only group of `groups`."""
    subjects = branch_subjects(repo, base)
    found = _commit_modes(subjects, groups)
    return {
        sha
        for sha, subject, mode in zip(_commits(repo, base), subjects, found, strict=True)
        if subject.startswith(TESTS_PREFIX) and mode is GroupMode.TESTS_ONLY
    }


def commits_without_red_check(repo: Path, base: str, groups: Sequence[GroupStep]) -> set[str]:
    """The commits of the branch no red check applies to, since only `tests_and_code` groups are
    red first: the tests commit of a test-only group, and every commit of a `no_code` or
    `refactor` group (the optional `test:` of the first, the lone `feat:` of both, which may
    edit tests mechanically)."""
    subjects = branch_subjects(repo, base)
    found = _commit_modes(subjects, groups)
    return {
        sha
        for sha, subject, mode in zip(_commits(repo, base), subjects, found, strict=True)
        if mode is not None
        and (
            (mode is GroupMode.TESTS_ONLY and subject.startswith(TESTS_PREFIX))
            or not mode.writes_tests
        )
    }


def _pair_problems(subjects: list[str], test_only: list[bool]) -> list[str]:
    """What is wrong with how `subjects` (oldest first) pair up: each `test:` commit is
    followed directly by a `feat:` commit with the same title, unless it is the commit of a
    test-only group (`test_only`, by position)."""
    problems: list[str] = []
    for index, subject in enumerate(subjects):
        if not subject.startswith(TESTS_PREFIX) or test_only[index]:
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
    groups: Sequence[GroupStep] = (),
) -> list[str]:
    """Check a branch's commits read as tests-then-implementation.

    `stubs` is the toolchain's check of a code file's content shipped beside tests, by
    path and content; it defaults to the Python one. `paired` also requires every `test:`
    commit to be followed directly by a `feat:` commit of the same title. `groups` is the
    unit's groups in order, each with its build mode; none given, each is `tests_and_code`.

    Returns every problem found, so one run shows the whole list rather than
    one problem per push.
    """
    shas = _commits(repo, base)
    if not shas:
        return [f"no commits between {base} and HEAD"]
    subjects = branch_subjects(repo, base)
    owners = _commit_modes(subjects, groups if paired else ())
    test_only = [
        mode is GroupMode.TESTS_ONLY and subject.startswith(TESTS_PREFIX)
        for subject, mode in zip(subjects, owners, strict=True)
    ]

    problems: list[str] = []
    kinds: list[str] = []
    stub_problems: dict[int, list[str]] = {}

    for index, sha in enumerate(shas):
        labels = classify_paths(_files_in(repo, sha), is_test)
        has_tests = any(kind == "test" for kind in labels.values())
        code_paths = [path for path, kind in labels.items() if kind == "code"]
        owner = owners[index]

        if (
            owner is not None
            and not owner.writes_tests
            and not subjects[index].startswith(TESTS_PREFIX)
        ):
            # The lone `feat:` of a group with no tests step may edit tests beside code (a
            # reorganization does, mechanically): no stubs to find, and it is code, not tests.
            kinds.append("code" if code_paths else "tests" if has_tests else "docs")
        elif has_tests and code_paths:
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
    # The mode of the group each substantive commit belongs to, none for a commit of no group.
    substantive_modes = [mode for kind, mode in zip(kinds, owners, strict=True) if kind != "docs"]
    # A unit with no `tests_and_code` group has no tests-first rule to keep.
    lenient = paired and bool(groups) and not any(group.mode.tests_first for group in groups)
    # A branch of documents only is a unit's whole work only when every group is `no_code`.
    documents_only = paired and bool(groups) and all(g.mode is GroupMode.NO_CODE for g in groups)

    if not substantive:
        return [] if documents_only else ["the branch changes no tests and no code"]

    # The headline first: a reviewer needs to know *which* rule was broken
    # before the file-by-file detail explaining how.
    first_substantive = next(i for i, kind in enumerate(kinds) if kind != "docs")
    first_mode = substantive_modes[0]
    first_exempt = first_mode is not None and not first_mode.writes_tests
    if not first_exempt and (substantive[0] != "tests" or first_substantive in stub_problems):
        problems.append(
            "the first commit contains implementation — a unit's first commit is its "
            "tests (plus stubs), so that they can be seen to fail"
        )

    for index in sorted(stub_problems):
        problems.extend(stub_problems[index])

    if "code" not in substantive and not lenient:
        problems.append("the branch has no implementation commit, only tests")

    for first, second, owning in zip(substantive, substantive[1:], substantive_modes, strict=False):
        exempt = owning is not None and not owning.tests_first
        if first == "tests" and second == "tests" and not exempt:
            problems.append(
                "two tests commits in a row — each batch of tests is followed by the "
                "implementation that makes it pass, so the pairs stay reviewable"
            )
            break

    if paired:
        problems.extend(_pair_problems(subjects, test_only))
        for group in groups:
            if group.mode is GroupMode.REFACTOR and f"{TESTS_PREFIX}{group.title}" in subjects:
                problems.append(
                    f"`{TESTS_PREFIX}{group.title}` is a tests commit for a reorganization, "
                    f"which takes a lone `{CODE_PREFIX}{group.title}`"
                )

    return problems
