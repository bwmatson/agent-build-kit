"""What a pull request changes, file by file, with the host's own line counts:
the figures a unit's actual size is summed from."""

from __future__ import annotations

import pytest

from agent_build_kit.forges.base import FileChange, RepoId
from agent_build_kit.forges.github import GitHubForge
from tests.forges.github_host import GitHubHost

pytestmark = pytest.mark.usefixtures("github_env")

REPO = RepoId(forge="github", account="example", name="app")
BASE = "/repos/example/app"
SHA = "0" * 40


def entry(filename: str, additions: int, deletions: int, **extra: object) -> dict:
    """A file as the pull request files endpoint sends it: counts beside the
    fields nothing here reads."""
    return {
        "sha": SHA,
        "filename": filename,
        "status": "modified",
        "additions": additions,
        "deletions": deletions,
        "changes": additions + deletions,
        "blob_url": f"https://github.example.test/example/app/blob/{SHA}/{filename}",
        "raw_url": f"https://github.example.test/example/app/raw/{SHA}/{filename}",
        "contents_url": f"https://api.github.example.test{BASE}/contents/{filename}",
        **extra,
    }


def test_each_file_carries_the_hosts_additions_and_deletions() -> None:
    host = GitHubHost(
        paged={
            f"{BASE}/pulls/7/files": [
                entry("src/app.py", 30, 4, patch="@@ -1 +1 @@"),
                entry("uv.lock", 500, 300),
                entry("docs/new.md", 12, 0, status="added"),
            ]
        }
    )

    changes = GitHubForge(http=host).pr_changes(REPO, 7)

    assert changes == [
        FileChange(path="src/app.py", additions=30, deletions=4),
        FileChange(path="uv.lock", additions=500, deletions=300),
        FileChange(path="docs/new.md", additions=12, deletions=0),
    ]


def test_a_renamed_file_is_counted_under_its_new_path() -> None:
    host = GitHubHost(
        paged={
            f"{BASE}/pulls/7/files": [
                entry("src/new.py", 2, 1, status="renamed", previous_filename="src/old.py")
            ]
        }
    )

    assert GitHubForge(http=host).pr_changes(REPO, 7) == [
        FileChange(path="src/new.py", additions=2, deletions=1)
    ]


def test_every_page_of_files_is_read() -> None:
    files = [entry(f"src/f{i}.py", i + 1, 0) for i in range(5)]
    host = GitHubHost(paged={f"{BASE}/pulls/7/files": files}, page_size=2)

    changes = GitHubForge(http=host).pr_changes(REPO, 7)

    assert [change.path for change in changes] == [f"src/f{i}.py" for i in range(5)]
    assert sum(change.additions for change in changes) == 15
