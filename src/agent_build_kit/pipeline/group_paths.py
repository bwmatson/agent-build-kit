"""The paths a task group names: one reader for project resolution and the e2e product-path
warning (spec: project-resolution)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from fnmatch import fnmatch
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from agent_build_kit.pipeline.commit_order import CONFIG_SUFFIXES, classify_paths

if TYPE_CHECKING:
    from agent_build_kit.pipeline.work_graph import TaskGroup

TEST_FOLDERS = frozenset({"tests", "__tests__"})
TEST_FILE_PATTERNS = ("test_*.py", "*_test.py", "*.test.*", "*.spec.*")
_TICKED = re.compile(r"`([^`]+)`")
_LINE_SUFFIX = re.compile(r":\d+$")
_EXTENSION = re.compile(r"\.[A-Za-z0-9]+$")
_NOT_A_PATH = re.compile(r"[\s=(<]")
# Lines of a group that say something other than which paths it changes.
_NOT_CHANGES = re.compile(
    r"^\s*(?:Not changed|Planning note|Reads|Paths|Needs|Support|Check|Manual|Separate|"
    r"Independent|Split|Priority|Acceptance|Tests):",
    re.I,
)
_VERIFY = re.compile(r"\bVerify:.*", re.I)
# A task that asks for tests, not code (`Test: ...`), or that only checks something, adds no
# implementation. `Run` is not a check: "Run the tracker through a new parent" is code.
_TEST_TASK = re.compile(r"tests?:", re.I)
CHECK_VERBS = ("Confirm", "Check", "Verify", "Read")
_CHECK_TASK = re.compile(rf"(?:{'|'.join(CHECK_VERBS)})\b", re.I)
_SENTENCE_END = re.compile(r"(?<=\.)\s+")
_NOT_A_CHANGE = re.compile(r"\b(?:unchanged|must not|do not)\b.*", re.I)


def _is_path_token(token: str) -> bool:
    """Whether a backticked token can be a path: not a flag, URL or variable, and no spaces,
    assignments, calls or placeholders."""
    return not (token.startswith(("-", "http", "$")) or _NOT_A_PATH.search(token))


def line_paths(line: str) -> list[str]:
    """The repo paths a task line names in backticks: tokens with a `/` or a file extension,
    without a trailing `:<line>`, `::<test id>` or `/`; URLs, flags, assignments, globs and
    symbols are skipped."""
    found: list[str] = []
    for token in _TICKED.findall(line):
        if not _is_path_token(token) or "*" in token:
            continue
        cleaned = _LINE_SUFFIX.sub("", token.split("::", 1)[0]).rstrip("/")
        if cleaned and ("/" in cleaned or _EXTENSION.search(cleaned)):
            found.append(cleaned)
    return found


def _glob_prefix(token: str) -> str | None:
    """The literal directory prefix of a glob token (`web/src/**` is `web/src/`), None when the
    token is not a glob or has no directory before it."""
    if not _is_path_token(token):
        return None
    at = [i for char in "*?[" if (i := token.find(char)) >= 0]
    if not at:
        return None
    prefix = token[: min(at)]
    prefix = prefix[: prefix.rfind("/") + 1]
    return prefix or None


def changed_paths(line: str, projects: Sequence[str]) -> list[str]:
    """The paths one line of a group names as changes: backticked paths, globs by their literal
    prefix and unticked words anchored on a declared project (`projects`), in the order they
    appear, leaving out a `Verify:` segment and a sentence from "unchanged", "must not" or
    "do not" on. A line that says what is not changed names none."""
    if _NOT_CHANGES.match(line):
        return []
    text = _VERIFY.sub("", line)
    anchored = (
        re.compile(rf"(?<![\w`/.-])(?:{'|'.join(re.escape(p) for p in projects)})/[^\s`,;)]*")
        if projects
        else None
    )
    found: list[str] = []
    for sentence in _SENTENCE_END.split(text):
        sentence = _NOT_A_CHANGE.sub("", sentence)
        found += line_paths(sentence)
        found += [prefix for t in _TICKED.findall(sentence) if (prefix := _glob_prefix(t))]
        if anchored:
            found += [w.rstrip(".:") for w in anchored.findall(_TICKED.sub(" ", sentence))]
    return list(dict.fromkeys(found))


def named_paths(group: TaskGroup, projects: Sequence[str]) -> list[str]:
    """The paths `group` names as changes: its `Paths:` line when it has one, else the paths of
    its lines that are changes, with globs by their literal prefix and unticked words anchored
    on a declared project's path (`projects`, as a heading writes them)."""
    if group.paths:
        return [_glob_prefix(entry) or entry.rstrip("/") for entry in group.paths]
    found = [path for line in group.body for path in changed_paths(line, projects)]
    return list(dict.fromkeys(found))


def allows_no_code(paths: Sequence[str]) -> bool:
    """Whether the paths a group names are all documents or configuration, so the group may be
    built without code. No path at all cannot be classified and allows nothing."""
    labels = classify_paths(list(paths))
    return bool(paths) and all(
        label == "docs" or (label == "code" and path.endswith(CONFIG_SUFFIXES))
        for path, label in labels.items()
    )


def _is_test_code(path: str) -> bool:
    """Whether `path` is test code for the tests-only rule: under a `tests` or `__tests__` folder,
    or a test file by name. A `test` or `testing` folder alone does not count: it may hold a
    product module."""
    pure = PurePosixPath(path)
    return bool(TEST_FOLDERS.intersection(pure.parts)) or any(
        fnmatch(pure.name, pattern) for pattern in TEST_FILE_PATTERNS
    )


def allows_tests_only(paths: Sequence[str]) -> bool:
    """Whether the paths a group names are test code (test files and test-support modules), at
    least one of them, with documents beside them. A source or configuration path, or no path at
    all, allows nothing.

    The repeat check re-runs only the collected `test_*.py` files a unit changed, so an edit to
    a test-support module pytest does not collect relies on the full run."""
    labels = classify_paths(list(paths))
    if not paths or any(labels[path] != "docs" and not _is_test_code(path) for path in paths):
        return False
    return any(labels[path] != "docs" for path in paths)


def _tasks(group: TaskGroup) -> list[tuple[str, list[str]]]:
    """Each task of `group` as (its first line's text, its lines): the task line and the lines
    that go on from it, up to the next task, a blank line or a line that is not about changes
    (`Needs:`, `Not changed:` ...)."""
    from agent_build_kit.pipeline.work_graph import TASK_LINE

    found: list[tuple[str, list[str]]] = []
    following = False
    for line in group.body:
        if (task := TASK_LINE.match(line)) is not None:
            found.append((task["text"], [line]))
            following = True
        elif following and line.strip() and not _NOT_CHANGES.match(line):
            found[-1][1].append(line)
        else:
            following = False
    return found


def _command_paths(line: str) -> list[str]:
    """The paths among the words of the backticked commands of `line` (`git mv a/b.py c/d.py`),
    which `line_paths` skips because a token with spaces is not a path. A `Verify:` segment and a
    sentence from "unchanged", "must not" or "do not" on are left out, as `changed_paths` does."""
    if _NOT_CHANGES.match(line):
        return []
    found: list[str] = []
    for sentence in _SENTENCE_END.split(_VERIFY.sub("", line)):
        for token in _TICKED.findall(_NOT_A_CHANGE.sub("", sentence)):
            found += line_paths(" ".join(f"`{word}`" for word in token.split()))
    return found


def _names_a_path(lines: Sequence[str], projects: Sequence[str]) -> bool:
    """Whether a task names a path: one `changed_paths` finds, or a word of a backticked command."""
    return any(changed_paths(line, projects) or _command_paths(line) for line in lines)


def names_unplaced_work(group: TaskGroup, projects: Sequence[str]) -> bool:
    """Whether a task of `group` is implementation work that names no path: not a test task, not
    a check (`CHECK_VERBS`), and no path in it. Such a group reads as code, whatever the paths
    its other tasks name. A `Paths:` line says what the group names, so the text is not read."""
    if group.paths:
        return False
    return any(
        not (_TEST_TASK.match(first) or _CHECK_TASK.match(first))
        and not _names_a_path(lines, projects)
        for first, lines in _tasks(group)
    )


def names_unplaced_glob(group: TaskGroup) -> bool:
    """Whether a line of `group` names a glob with no folder before it (`*.py`, `**/*.py`), which
    may change any file: `named_paths` skips it, so a caller that must be conservative asks."""
    if group.paths:
        return False
    for line in group.body:
        if _NOT_CHANGES.match(line):
            continue
        for sentence in _SENTENCE_END.split(_VERIFY.sub("", line)):
            for token in _TICKED.findall(_NOT_A_CHANGE.sub("", sentence)):
                if _is_path_token(token) and "*" in token and _glob_prefix(token) is None:
                    return True
    return False
