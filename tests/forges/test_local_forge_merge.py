"""A local pull request is merged when git says so (spec: local-forge).

Nothing here is faked: a pull request is opened on a real repository with no remote, a person's
merge is done with git, and the forge's listing is read back.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_build_kit.forges import PullRequest
from agent_build_kit.forges.local import LocalForge, LocalPrUnreadable
from agent_build_kit.pipeline.units import MERGED
from tests.conftest import make_installation
from tests.factories import git, init_repo

HEAD = "spec/feature/2"


def commit(repo: Path, name: str, text: str = "x\n") -> None:
    (repo / name).parent.mkdir(parents=True, exist_ok=True)
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

    def open(self, head: str, files: tuple[str, ...] = ()) -> int:
        """A pull request for `head`, whose branch (made from `main` when `files` are given)
        adds each of those files; with none, no such branch exists."""
        if files:
            git(self.repo, "checkout", "-q", "-b", head, "main")
            for name in files:
                commit(self.repo, name, f"{name}\n")
            git(self.repo, "checkout", "-q", "main")
        return self.forge.create_pr(self.id, head=head, base="main", title="t", body="b")

    def files(self, number: int | None = None) -> list[str]:
        return sorted(self.forge.pr_files(self.id, number or self.number))


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


def rebase_and_fast_forward(local: Local) -> None:
    commit(local.repo, "elsewhere.txt")
    git(local.repo, "rebase", "-q", "main", HEAD)
    git(local.repo, "checkout", "-q", "main")
    git(local.repo, "merge", "-q", "--ff-only", HEAD)


def test_a_rebase_merge_is_seen_as_merged_by_patch_identity(local: Local) -> None:
    assert local.listed().state == "open"

    rebase_and_fast_forward(local)

    assert local.listed().state == MERGED


def test_a_rebase_merge_stays_merged_when_the_branch_is_deleted(local: Local) -> None:
    assert local.listed().state == "open"
    rebase_and_fast_forward(local)
    git(local.repo, "branch", "-q", "-D", HEAD)

    assert local.listed().state == MERGED


def test_a_branch_with_one_commit_not_in_the_trunk_is_not_a_rebase_merge(local: Local) -> None:
    assert local.listed().state == "open"
    # only the first of the two commits reaches the trunk, cherry-picked
    git(local.repo, "cherry-pick", f"{HEAD}~1")

    assert local.listed().state == "open"


def stored_pull(local: Local) -> dict:
    stored = json.loads((local.forge.state_dir / "local-prs.json").read_text())
    return stored[next(iter(stored))][0]


def rewrite_pull(local: Local, **fields: str | None) -> None:
    """Set each field of the stored pull request, or delete it when the value is None."""
    path = local.forge.state_dir / "local-prs.json"
    stored = json.loads(path.read_text())
    pull = stored[next(iter(stored))][0]
    for name, value in fields.items():
        if value is None:
            del pull[name]
        else:
            pull[name] = value
    path.write_text(json.dumps(stored))


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


# --- the files a pull request changed -------------------------------------------------


def test_a_pull_request_lists_the_files_its_branch_changed_before_and_after_it_lands(
    local: Local,
) -> None:
    assert local.files() == ["a.txt", "b.txt"]

    git(local.repo, "merge", "-q", "--ff-only", HEAD)
    local.listed()

    assert local.files() == ["a.txt", "b.txt"]


def test_a_pull_request_whose_branch_was_deleted_after_landing_still_lists_its_files(
    local: Local,
) -> None:
    git(local.repo, "merge", "-q", "--ff-only", HEAD)
    local.listed()
    git(local.repo, "branch", "-q", "-D", HEAD)

    assert local.files() == ["a.txt", "b.txt"]


def test_a_branch_rebased_onto_an_advanced_trunk_lists_only_its_own_files(local: Local) -> None:
    rebase_and_fast_forward(local)
    local.listed()

    assert local.files() == ["a.txt", "b.txt"]


def test_a_branch_rebased_and_settled_before_it_lands_lists_only_its_own_files(
    local: Local,
) -> None:
    commit(local.repo, "elsewhere.txt")
    git(local.repo, "rebase", "-q", "main", HEAD)
    git(local.repo, "checkout", "-q", "main")
    local.listed()
    git(local.repo, "merge", "-q", "--ff-only", HEAD)

    assert local.files() == ["a.txt", "b.txt"]


def test_a_non_ascii_file_name_is_listed_as_it_is_written(local: Local) -> None:
    number = local.open("spec/feature/3", ("src/café.py",))

    assert local.files(number) == ["src/café.py"]


def test_a_pull_request_with_no_branch_cannot_list_its_files(local: Local) -> None:
    number = local.open("spec/feature/3")

    with pytest.raises(LocalPrUnreadable, match=f"pull request {number}"):
        local.files(number)


def test_a_record_without_a_fork_point_cannot_list_its_files(local: Local) -> None:
    rewrite_pull(local, fork=None)

    with pytest.raises(LocalPrUnreadable, match="fork point"):
        local.files()


def test_a_fork_point_git_does_not_know_cannot_list_its_files(local: Local) -> None:
    rewrite_pull(local, fork="0" * 40)

    with pytest.raises(LocalPrUnreadable, match=f"pull request {local.number}"):
        local.files()


def test_a_pull_request_the_forge_does_not_hold_cannot_list_its_files(local: Local) -> None:
    with pytest.raises(LocalPrUnreadable, match="no such pull request"):
        local.files(99)
