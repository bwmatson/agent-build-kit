"""On GitHub the paths of a pull request's files come from its full listing."""

from __future__ import annotations

import pytest

from agent_build_kit.forges.base import FileChange, RepoId
from agent_build_kit.forges.github import GitHubForge
from tests.forges.github_host import GitHubHost

pytestmark = pytest.mark.usefixtures("github_env")

REPO = RepoId(forge="github", account="example", name="app")


class Listing(GitHubForge):
    """A forge whose full listing is scripted, counting how often it is asked."""

    def __init__(self) -> None:
        super().__init__(http=GitHubHost())
        self.listed = 0

    def pr_changes(self, repo: RepoId, pr: int) -> list[FileChange]:
        self.listed += 1
        return [
            FileChange(path="src/app.py", additions=3, deletions=1),
            FileChange(path="docs/new.md", additions=2, deletions=0),
        ]


def test_the_paths_are_the_paths_of_the_full_listing_asked_for_once() -> None:
    forge = Listing()

    assert forge.pr_files(REPO, 7) == ["src/app.py", "docs/new.md"]
    assert forge.listed == 1
