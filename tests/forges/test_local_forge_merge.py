"""A local pull request is merged when git says so (spec: local-forge).

Nothing here is faked: a pull request is opened on a real repository with no remote, a person's
merge is done with git, and the forge's listing is read back.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_build_kit.forges import PullRequest
from agent_build_kit.forges.local import LocalForge
from agent_build_kit.pipeline.units import MERGED
from tests.conftest import make_installation
from tests.factories import git, init_repo

HEAD = "spec/feature/2"


def commit(repo: Path, name: str, text: str = "x\n") -> None:
    (repo / name).write_text(text)
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", f"add {name}")


class Local:
    """A repo with no remote, on `main`, with a unit branch two commits ahead of it."""

    def __init__(self, tmp_path: Path) -> None:
        self.repo = init_repo(tmp_path / "app")
        commit(self.repo, "base.txt")
        git(self.repo, "checkout", "-q", "-b", HEAD)
        commit(self.repo, "a.txt", "a\n")
        commit(self.repo, "b.txt", "b\n")
        git(self.repo, "checkout", "-q", "main")
        self.installation = make_installation(
            tmp_path / "planning", repos={"app": {"path": str(self.repo), "forge": "local"}}
        )
        self.forge = LocalForge(self.installation.state_dir)
        self.id = self.forge.identity(self.installation.repo("app"))
        self.number = self.forge.create_pr(
            self.id, head=HEAD, base="main", title="Feature", body="Body"
        )

    def listed(self) -> PullRequest:
        (pull,) = [p for p in self.forge.list_prs(self.id) if p.number == self.number]
        return pull


@pytest.fixture
def local(tmp_path: Path) -> Local:
    return Local(tmp_path)


def test_a_merge_commit_is_seen_as_merged(local: Local) -> None:
    commit(local.repo, "elsewhere.txt")
    assert local.listed().state == "open"

    git(local.repo, "merge", "-q", "--no-ff", "-m", "merge the feature", HEAD)

    assert local.listed().state == MERGED


def test_a_fast_forward_is_seen_as_merged(local: Local) -> None:
    assert local.listed().state == "open"

    git(local.repo, "merge", "-q", "--ff-only", HEAD)

    assert local.listed().state == MERGED


def test_a_squash_is_seen_as_merged_by_patch_identity(local: Local) -> None:
    commit(local.repo, "elsewhere.txt")
    git(local.repo, "merge", "-q", "--squash", HEAD)
    git(local.repo, "commit", "-q", "-m", "the feature, squashed")
    commit(local.repo, "later.txt")

    assert local.listed().state == MERGED


def test_a_branch_with_more_than_the_squashed_change_is_not_merged(local: Local) -> None:
    git(local.repo, "merge", "-q", "--squash", HEAD)
    git(local.repo, "commit", "-q", "-m", "the feature, squashed")

    git(local.repo, "checkout", "-q", HEAD)
    commit(local.repo, "c.txt", "c\n")
    git(local.repo, "checkout", "-q", "main")

    assert local.listed().state == "open"


def test_a_fast_forward_merge_stays_merged_when_the_branch_is_deleted(local: Local) -> None:
    assert local.listed().state == "open"
    git(local.repo, "merge", "-q", "--ff-only", HEAD)
    git(local.repo, "branch", "-q", "-D", HEAD)

    assert local.listed().state == MERGED
    assert (local.forge.record(local.id, local.number) or {})["state"] == MERGED
    assert local.forge.find_pr(local.id, head=HEAD) is None


def test_a_squash_merge_stays_merged_when_the_branch_is_deleted(local: Local) -> None:
    assert local.listed().state == "open"
    commit(local.repo, "elsewhere.txt")
    git(local.repo, "merge", "-q", "--squash", HEAD)
    git(local.repo, "commit", "-q", "-m", "the feature, squashed")
    git(local.repo, "branch", "-q", "-D", HEAD)

    assert local.listed().state == MERGED


def test_a_branch_deleted_without_a_merge_is_still_open(local: Local) -> None:
    assert local.listed().state == "open"
    git(local.repo, "branch", "-q", "-D", HEAD)

    assert local.listed().state == "open"


def stored_pull(local: Local) -> dict:
    stored = json.loads((local.forge.state_dir / "local-prs.json").read_text())
    return stored[next(iter(stored))][0]


def test_a_branch_reset_onto_the_trunk_is_not_merged(local: Local) -> None:
    assert local.listed().state == "open"
    tip = stored_pull(local)["tip"]

    git(local.repo, "branch", "-f", HEAD, "main")

    assert local.listed().state == "open"
    assert stored_pull(local)["state"] == "open"
    assert stored_pull(local)["tip"] == tip

    # new work on the reset branch is its own, and the pull request stays open
    git(local.repo, "checkout", "-q", HEAD)
    commit(local.repo, "again.txt")
    git(local.repo, "checkout", "-q", "main")

    assert local.listed().state == "open"
    assert stored_pull(local)["tip"] == git(local.repo, "rev-parse", HEAD)
