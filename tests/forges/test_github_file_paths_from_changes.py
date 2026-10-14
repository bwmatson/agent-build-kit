"""On GitHub the paths of a pull request's files come from its full listing, read once."""

from __future__ import annotations

import pytest

from agent_build_kit.forges.base import RepoId
from agent_build_kit.forges.github import GitHubForge
from tests.forges.github_host import GitHubHost
from tests.forges.test_github_rest_changes import BASE, entry

pytestmark = pytest.mark.usefixtures("github_env")

REPO = RepoId(forge="github", account="example", name="app")


def test_the_paths_are_the_paths_of_the_full_listing_asked_for_once() -> None:
    path = f"{BASE}/pulls/7/files"
    host = GitHubHost(paged={path: [entry("src/app.py", 3, 1), entry("docs/new.md", 2, 0)]})

    paths = GitHubForge(http=host).pr_files(REPO, 7)

    assert paths == ["src/app.py", "docs/new.md"]
    assert len(host.calls("GET", path)) == 1
