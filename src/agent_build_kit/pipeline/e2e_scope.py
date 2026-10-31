"""What an `[e2e-test]` group may name: tests, test support, docs, the changelog and declared
support. The classifier shared by the `abk tags` warning and
the build's checks guard, and the warning itself."""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path

from agent_build_kit import profiles
from agent_build_kit.config import RepoConfig
from agent_build_kit.model import TestTier
from agent_build_kit.pipeline.group_paths import changed_paths
from agent_build_kit.pipeline.work_graph import TASK_LINE, TaskGroup
from agent_build_kit.profiles.base import is_doc_path

_TASK_NUMBER = re.compile(r"\d+\.\d+")
_SCRIPTS = "scripts/"


def is_test_path(path: str, repo: RepoConfig | None) -> bool:
    """Whether `path` is a test path of the repo's profile for the project the path belongs to."""
    fallback = profiles.get(repo.profile if repo else "python-uv")
    return profiles.for_path(repo.projects if repo else [], path, fallback).is_test_path(path)


def _is_declared(path: str, support: Sequence[str]) -> bool:
    return any(
        path.startswith(entry) if entry.endswith("/") else path == entry for entry in support
    )


def is_product_path(path: str, repo: RepoConfig | None, support: Sequence[str] = ()) -> bool:
    """Whether `path` is none of: a test path of the repo's profile for the path's project, a
    doc path, the repo's changelog, or declared support (a trailing `/` covers a directory)."""
    changelog = repo.changelog if repo else "CHANGELOG.md"
    return not (
        is_test_path(path, repo)
        or is_doc_path(path)
        or path == changelog
        or _is_declared(path, support)
    )


def unscoped_task_paths(
    paths: Sequence[str], repo: RepoConfig | None, support: Sequence[str] = ()
) -> list[str]:
    """The paths of one task line that are product code: `is_product_path`, except that a
    `scripts/` path is allowed when the line also names a test path."""
    names_test = any(is_test_path(path, repo) for path in paths)
    return [
        path
        for path in paths
        if is_product_path(path, repo, support) and not (names_test and path.startswith(_SCRIPTS))
    ]


_CHANGING_VERBS = frozenset(
    {"fix", "change", "add", "implement", "update", "refactor", "remove", "rename", "make"}
)
# A documentation word exempts a task only as the object of the verb, near the start of the line.
_OBJECT_WORDS = 5
_NOT_A_CHANGE = re.compile(r"\b(docs?|documentation|changelog|readme)\b", re.I)


def _e2e_task_lines(
    path: Path, groups: Sequence[TaskGroup]
) -> Iterator[tuple[int, TaskGroup, re.Match[str]]]:
    """The task lines of the `[e2e-test]` groups of a tasks file: line number, group, match."""
    headings = {g.line: g for g in groups}
    group = None
    for index, text in enumerate(path.read_text().splitlines(), start=1):
        if text.startswith("## "):
            group = headings.get(index)
        if group is None or group.tier != TestTier.E2E_TEST:
            continue
        matched = TASK_LINE.match(text)
        if matched:
            yield index, group, matched


def task_wording_warnings(path: Path, groups: Sequence[TaskGroup]) -> list[str]:
    """One warning per task of an `[e2e-test]` group that asks in words for a change to the
    product: not a `Test:`, `Support:`, documentation or changelog task, it begins with a
    changing verb. A task that names any path is placed by it: a product path is left to
    `product_path_warnings`, and a test, doc or support path is not a product change."""
    warnings: list[str] = []
    for index, group, matched in _e2e_task_lines(path, groups):
        text = matched["text"]
        words = text.split()
        if not words or words[0].lower().rstrip(":,;.") not in _CHANGING_VERBS:
            continue
        if _NOT_A_CHANGE.search(" ".join(words[:_OBJECT_WORDS])):
            continue
        if changed_paths(text, ()):
            continue
        warnings.append(
            f"{path}:line {index}: warning: group {group.number}: task "
            f"{group.number}.{matched['number']} asks for a change to the product ({text!r}); "
            "an [e2e-test] unit changes no product code. Report a product fault as a "
            "product-defect block, or, when the defect is already known, write the "
            "[unit-test] group first and have this group Needs: it"
        )
    return warnings


def product_path_warnings(
    path: Path, groups: Sequence[TaskGroup], repos: Mapping[str, RepoConfig]
) -> list[str]:
    """One warning per path and `[e2e-test]` group of a tasks file that names product code,
    as `abk tags` and `abk check` print it; `groups` are the file's as validated."""
    warnings: list[str] = []
    seen: set[tuple[int, str]] = set()
    for index, group, matched in _e2e_task_lines(path, groups):
        text = matched.string
        number = _TASK_NUMBER.search(text)
        repo = repos.get(group.repo)
        paths = changed_paths(text, ())
        for named in unscoped_task_paths(paths, repo, group.support):
            if (group.number, named) in seen:
                continue
            seen.add((group.number, named))
            warnings.append(
                f"{path}:line {index}: warning: group {group.number}: task "
                f"{number[0] if number else '?'} names {named}, which is not a test path, a "
                "doc, the changelog or declared support; an [e2e-test] group holds tests, and "
                "a product defect a live test finds is fixed by a [unit-test] change the "
                "pipeline files"
            )
    return warnings
