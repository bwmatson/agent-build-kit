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
import re
import subprocess
from collections.abc import Callable, Collection, Sequence
from pathlib import Path, PurePosixPath
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
GROUP_TRAILER = "Group"  # the trailer key; its value is `<change>/<number>`
STUB_BODY_HINT = "only `raise NotImplementedError`"

# A path is a test if any part of it is a tests directory, so this holds for a
# monorepo (svc-a/tests/...) as well as a flat one (tests/...). Fixtures and
# conftest live there too and count the same way.
TEST_DIR_NAMES = frozenset({"tests", "test", "__tests__"})
TEST_FILE_PREFIXES = ("test_",)
TEST_FILE_SUFFIXES = ("_test.py", ".test.ts", ".spec.ts")

# Neither tests nor implementation: a README or a design note may ride along
# with either commit, because forcing a separate branch for a one-line doc fix
# would just push authors to skip the rule.
DOC_SUFFIXES = (".md", ".rst", ".txt")

# Configuration a group may change without writing code.
CONFIG_SUFFIXES = (".yml", ".yaml", ".toml", ".json", ".ini", ".cfg")


def extended_test_file(path: str, exists: Callable[[str], bool]) -> tuple[str, str] | None:
    """The existing test file the new test file `path` extends, with the subject of `path`.

    The file sits in the same folder, has the same naming form (a prefix of `TEST_FILE_PREFIXES`
    or a suffix of `TEST_FILE_SUFFIXES`) and a subject that is a leading part of `path`'s own
    (`test_widget.py` for `test_widget_label.py`, `widget.test.ts` for `widget.label.test.ts`).
    When several qualify the one with the shortest subject wins. `exists(candidate)` says
    whether a path holds a file."""
    pure = PurePosixPath(path)
    name = pure.name
    parts: tuple[str, str, str] | None = None
    for prefix in TEST_FILE_PREFIXES:
        if name.startswith(prefix):
            parts = (prefix, pure.stem[len(prefix) :], pure.suffix)
            break
    if parts is None:
        for suffix in TEST_FILE_SUFFIXES:
            if name.endswith(suffix):
                parts = ("", name[: -len(suffix)], suffix)
                break
    if parts is None:
        return None
    head, subject, tail = parts
    for found in re.finditer(r"[_.]", subject):
        if found.start() == 0:
            continue
        sibling = pure.with_name(f"{head}{subject[: found.start()]}{tail}").as_posix()
        if exists(sibling):
            return sibling, subject
    return None


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
    return [sha for sha, _ in branch_commit_subjects(repo, base)]


def _files_in(repo: Path, sha: str) -> list[str]:
    out = git_out(repo, "show", "--name-only", "--pretty=format:", sha)
    return [line for line in out.splitlines() if line]


def _file_at(repo: Path, sha: str, path: str) -> str:
    try:
        return git_out(repo, "show", f"{sha}:{path}")
    except subprocess.CalledProcessError:
        return ""  # Deleted in this commit; nothing to vouch for.


def recorded_built(repo: Path, sha: str, recorded: Collection[str] | None = None) -> bool:
    """Whether the commit is marked `Already-built: yes` and holds no file. A file keeps the
    marker from excusing real work. When `recorded` is given, the commit must also be one the
    pipeline recorded as built, so a marker the agent wrote excuses nothing."""
    if recorded is not None and sha not in recorded:
        return False
    marked = git_out(
        repo, "log", "-1", f"--format=%(trailers:key={ALREADY_BUILT_TRAILER},valueonly)", sha
    )
    return marked.strip() == "yes" and not _files_in(repo, sha)


# The subject of a commit the pipeline writes itself; the group walk leaves it out.
CHANGELOG_SEPARATED = "changelog: separate bullets joined by the union merge"
PIPELINE_SUBJECTS = frozenset({CHANGELOG_SEPARATED})


def branch_commit_subjects(repo: Path, base: str, ref: str = "HEAD") -> list[tuple[str, str]]:
    """The hash and subject of each commit the branch at `ref` carries beyond `base`, oldest
    first, without the commits the pipeline makes itself (`PIPELINE_SUBJECTS`), which belong to
    no group."""
    out = git_out(repo, "log", "--reverse", "--format=%H%x00%s", f"{base}..{ref}")
    found = [tuple(line.split("\0", 1)) for line in out.splitlines()]
    return [pair for pair in found if pair[1] not in PIPELINE_SUBJECTS]  # pyrefly: ignore[bad-return]


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
    notes: tuple[str, ...] = ()  # commits counted by their `Group:` trailer despite an older title
    # The subject standing where the walk stopped, "" when the branch ends there or every group is
    # done. A report for the stop's text, NOT part of equality or the hash: two progresses that
    # differ only here compare equal, so an assertion on a progress cannot catch a wrong value.
    at_place: str = ""

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, GroupProgress):
            return NotImplemented
        return self.model_dump(exclude={"at_place"}) == other.model_dump(exclude={"at_place"})

    def __hash__(self) -> int:
        return hash((self.done, self.tests_made, self.lone_feat, self.notes))


def group_key(step: GroupStep) -> str:
    """The value of the `Group:` trailer the commits of `step` carry: `<change>/<number>`."""
    return f"{Path(step.change_dir).name}/{step.number}"


def branch_commit_trailers(repo: Path, base: str, ref: str = "HEAD") -> list[str]:
    """The `Group:` trailer value of each commit the branch at `ref` carries beyond `base`, oldest
    first, "" for a commit with none; aligned with `branch_commit_subjects`."""
    out = git_out(
        repo,
        "log",
        "--reverse",
        f"--format=%s%x01%(trailers:key={GROUP_TRAILER},valueonly,separator=%x2C)%x00",
        f"{base}..{ref}",
    )
    entries = [value.split("\x01", 1) for value in out.split("\0")[:-1]]
    return [
        trailer.strip() for subject, trailer in entries if subject.strip() not in PIPELINE_SUBJECTS
    ]


def _is_commit(
    subjects: list[str], trailers: Sequence[str], index: int, prefix: str, title: str, key: str
) -> bool:
    """Whether the commit at `index` is the `prefix` commit of the group `key` titled `title`: by
    its `Group:` trailer when it has one (its title is then free), else by the exact subject."""
    if index >= len(subjects):
        return False
    trailer = trailers[index] if index < len(trailers) else ""
    if trailer:
        return trailer == key and subjects[index].startswith(prefix)
    return subjects[index] == f"{prefix}{title}"


def _group_size(
    subjects: list[str],
    position: int,
    title: str,
    mode: GroupMode,
    trailers: Sequence[str] = (),
    key: str = "",
) -> int | None:
    """How many commits a finished group takes from `subjects` at `position`, None when the
    group is not finished there. A `tests_and_code` group takes a `test:` then a `feat:`; a
    `tests_only` group its `test:` alone; a `no_code` group a lone `feat:` or that pair; a
    `refactor` group a lone `feat:`. A commit whose `trailers` entry is set is the group `key`'s
    by that value, whatever its title."""

    def is_commit(index: int, prefix: str) -> bool:
        return _is_commit(subjects, trailers, index, prefix, title, key)

    if mode.accepts_tests_commit and is_commit(position, TESTS_PREFIX):
        if mode is GroupMode.TESTS_ONLY:
            return 1
        return 2 if is_commit(position + 1, CODE_PREFIX) else None
    if mode in (GroupMode.NO_CODE, GroupMode.REFACTOR) and is_commit(position, CODE_PREFIX):
        return 1
    return None


def _stale_note(subjects: list[str], title: str, key: str, start: int, size: int) -> str:
    """The note for commits counted by their trailer under an older title, "" when each has the
    group's own subject."""
    stale = [
        subject
        for subject in subjects[start : start + size]
        if subject not in (f"{TESTS_PREFIX}{title}", f"{CODE_PREFIX}{title}")
    ]
    if not stale:
        return ""
    names = " and ".join(f"`{subject}`" for subject in stale)
    return (
        f"{names} counted for group {key} by its Group trailer, though it is now titled `{title}`"
    )


def group_progress(
    subjects: list[str],
    titles: Sequence[str],
    modes: Sequence[GroupMode] = (),
    trailers: Sequence[str] = (),
    keys: Sequence[str] = (),
) -> GroupProgress:
    """Walk the groups in the unit's order, each taking the commits its mode calls for with its
    title from the front of `subjects` (oldest first); `modes` is by position, like `titles`, and
    a group with none is `tests_and_code`. The position in the unit, not the title, tells groups
    apart, so two groups with one title are told apart. A branch that does not begin with the
    first group's commits has made no progress. `trailers` is each subject's `Group:` value and
    `keys` each group's, by position: a commit whose trailer is its group's counts whatever its
    title, and one whose trailer names another group does not count."""
    position = 0
    notes: list[str] = []
    for done, title in enumerate(titles):
        mode = mode_at(modes, done)
        key = keys[done] if done < len(keys) else ""
        size = _group_size(subjects, position, title, mode, trailers, key)
        if size is None:
            at = subjects[position] if position < len(subjects) else ""
            if (
                mode.accepts_tests_commit
                and mode.writes_code
                and _is_commit(subjects, trailers, position, TESTS_PREFIX, title, key)
            ):
                return GroupProgress(done=done, tests_made=True, notes=tuple(notes), at_place=at)
            lone = mode is GroupMode.TESTS_AND_CODE and _is_commit(
                subjects, trailers, position, CODE_PREFIX, title, key
            )
            return GroupProgress(
                done=done,
                tests_made=False,
                lone_feat=at if lone else "",
                notes=tuple(notes),
                at_place=at,
            )
        if note := _stale_note(subjects, title, key, position, size):
            notes.append(note)
        position += size
    return GroupProgress(done=len(titles), tests_made=False, notes=tuple(notes))


def steps_progress(
    subjects: list[str], trailers: Sequence[str], steps: Sequence[GroupStep]
) -> GroupProgress:
    """`group_progress` of the unit's `steps`: the one place their titles, modes and `Group:` keys
    are put together, so a walk of the branch cannot leave the trailers or keys out."""
    return group_progress(
        subjects,
        [step.title for step in steps],
        [step.mode for step in steps],
        trailers,
        [group_key(step) for step in steps],
    )


def walk_group_progress(
    repo: Path, base: str, steps: Sequence[GroupStep], ref: str = "HEAD"
) -> GroupProgress:
    """`group_progress` over the branch at `ref`, matching a commit to its group by the number in
    its `Group:` trailer and, for a commit with none, by its title; `notes` names each pair
    counted under an older title."""
    return steps_progress(
        [subject for _, subject in branch_commit_subjects(repo, base, ref)],
        branch_commit_trailers(repo, base, ref),
        steps,
    )


def adopted_names(
    unit_title: str,
    steps: Sequence[GroupStep],
    subjects: list[str],
    trailers: Sequence[str] = (),
) -> tuple[str, str]:
    """The subject and the `Group:` trailer value of the commit a person's adopted changes become,
    both read from one walk of `subjects` (oldest first, with their `trailers`), so they name the
    same group. The subject is what the counter takes for the commit the build expected next:
    `test:` or `feat:` with the title of the group reached, `fix: <last title> (adopted)` once
    every group has its commits. The trailer is that group's, the last group's once every one has
    its commits. `steps` is empty for a unit that is not built in stubbed groups, which takes
    `unit_title` and no trailer."""
    if not steps:
        subject = (
            f"{FIX_PREFIX}{unit_title} (adopted)" if subjects else f"{CODE_PREFIX}{unit_title}"
        )
        return subject, ""
    progress = steps_progress(subjects, trailers, steps)
    if progress.done >= len(steps):
        return f"{FIX_PREFIX}{steps[-1].title} (adopted)", group_key(steps[-1])
    reached = steps[progress.done]
    prefix = CODE_PREFIX if progress.tests_made or not reached.mode.writes_tests else TESTS_PREFIX
    return f"{prefix}{reached.title}", group_key(reached)


def adopted_subject(
    unit_title: str,
    steps: Sequence[GroupStep],
    subjects: list[str],
    trailers: Sequence[str] = (),
) -> str:
    """The subject of the commit a person's adopted changes become: the first of `adopted_names`."""
    return adopted_names(unit_title, steps, subjects, trailers)[0]


def superseded_pairs(
    repo: Path,
    ref: str,
    base: str,
    titles: Sequence[str],
    modes: Sequence[GroupMode],
    keys: Sequence[str] = (),
) -> list[list[str]] | None:
    """The commits of each group on the branch at `ref`, oldest group first, when the branch
    beyond `base` is exactly the commits each of the groups (`titles`, by position, with `modes`
    and, matched by trailer, `keys`) takes, in order; None for any other branch, which has a
    commit that belongs to no group or lacks one."""
    found = branch_commit_subjects(repo, base, ref)
    shas = [sha for sha, _ in found]
    subjects = [subject for _, subject in found]
    trailers = branch_commit_trailers(repo, base, ref)
    taken = 0
    groups: list[list[str]] = []
    for index, title in enumerate(titles):
        key = keys[index] if index < len(keys) else ""
        size = _group_size(subjects, taken, title, mode_at(modes, index), trailers, key)
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


def _commit_modes(
    subjects: list[str], groups: Sequence[GroupStep], trailers: Sequence[str] = ()
) -> list[GroupMode | None]:
    """For each subject, the mode of the group whose commit it is, None for a commit that belongs
    to no group. The groups are walked in order, each taking the commits its mode calls for with
    its title (or its `Group:` trailer), so position tells two groups with one title apart."""
    found: list[GroupMode | None] = [None] * len(subjects)
    position = 0
    for group in groups:
        key = group_key(group)
        size = _group_size(subjects, position, group.title, group.mode, trailers, key)
        if size is None:
            if _is_commit(subjects, trailers, position, TESTS_PREFIX, group.title, key):
                found[position] = group.mode if group.mode.accepts_tests_commit else None
            break
        found[position : position + size] = [group.mode] * size
        position += size
    return found


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


def _pair_problems(
    subjects: list[str], test_only: list[bool], trailers: Sequence[str] = ()
) -> list[str]:
    """What is wrong with how `subjects` (oldest first) pair up: each `test:` commit is
    followed directly by a `feat:` commit with the same title, or with the same `Group:` trailer,
    unless it is the commit of a test-only group (`test_only`, by position)."""
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
        trailer = trailers[index] if index < len(trailers) else ""
        same_group = (
            bool(trailer)
            and following is not None
            and following.startswith(CODE_PREFIX)
            and trailers[index + 1] == trailer
        )
        if following != f"{CODE_PREFIX}{title}" and not same_group:
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
    trailers = branch_commit_trailers(repo, base)
    owners = _commit_modes(subjects, groups if paired else (), trailers)
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
        elif (
            owner is not None
            and subjects[index].startswith(CODE_PREFIX)
            and (test_files := [path for path, kind in labels.items() if kind == "test"])
        ):
            # The `feat:` of a group with a tests step: every edit to a test file is in the
            # `test:` commit, which is where it has been seen to fail.
            named = ", ".join(f"`{path}`" for path in test_files)
            problems.append(
                f"`{subjects[index]}` changes {named} — every edit to a test file of a group "
                f"with a tests step is in its `{TESTS_PREFIX}` commit, and the "
                f"`{CODE_PREFIX}` commit touches none"
            )
            kinds.append("code")
        elif paired and groups and owner is None and subjects[index].startswith(FIX_PREFIX):
            # A `fix:` commit after the groups' commits may correct a test beside code: it is
            # neither a tests commit nor stub-checked, whatever it holds.
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
        problems.extend(_pair_problems(subjects, test_only, trailers))
        if (title := _refactor_given_tests(subjects, groups, trailers)) is not None:
            problems.append(
                f"`{TESTS_PREFIX}{title}` is a tests commit for a reorganization, "
                f"which takes a lone `{CODE_PREFIX}{title}`"
            )

    return problems


def _refactor_given_tests(
    subjects: list[str], groups: Sequence[GroupStep], trailers: Sequence[str] = ()
) -> str | None:
    """The title of the `refactor` group the walk of `groups` over `subjects` stops at because its
    place holds its own `test:` commit, None when the walk stops elsewhere or not at all. By
    position, so a `refactor` group does not take the tests commit of an earlier group with its
    title."""
    position = 0
    for group in groups:
        key = group_key(group)
        size = _group_size(subjects, position, group.title, group.mode, trailers, key)
        if size is None:
            own_tests = _is_commit(subjects, trailers, position, TESTS_PREFIX, group.title, key)
            return group.title if group.mode is GroupMode.REFACTOR and own_tests else None
        position += size
    return None
