"""What an `[e2e-test]` group may name: tests, test support, docs, the changelog and declared
support. The classifier shared by the `abk tags` warning and
the build's checks guard, and the warning itself."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path

from agent_build_kit import profiles
from agent_build_kit.config import RepoConfig
from agent_build_kit.model import TestTier
from agent_build_kit.pipeline.group_paths import changed_paths
from agent_build_kit.pipeline.work_graph import TASK_LINE, TaskGroup, project_tags
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


def product_path_warnings(
    path: Path, groups: Sequence[TaskGroup], repos: Mapping[str, RepoConfig]
) -> list[str]:
    """One warning per path and `[e2e-test]` group of a tasks file that names product code,
    as `abk tags` and `abk check` print it; `groups` are the file's as validated."""
    headings = {g.line: g for g in groups}
    warnings: list[str] = []
    seen: set[tuple[int, str]] = set()
    group = None
    for index, text in enumerate(path.read_text().splitlines(), start=1):
        if text.startswith("## "):
            group = headings.get(index)
        if group is None or group.tier != TestTier.E2E_TEST or not TASK_LINE.match(text):
            continue
        number = _TASK_NUMBER.search(text)
        repo = repos.get(group.repo)
        paths = changed_paths(text, project_tags(repo.projects) if repo else ())
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
