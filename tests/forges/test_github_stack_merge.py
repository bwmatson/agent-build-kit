"""The commit of each pull request of a stack merged at once (spec: stacked-merge-landing).

GitHub's documentation does not give the API's answers for a stack merge and none has been
recorded, so the host's answers here are hand-written ASSUMPTIONS from that documentation, not
recordings: a distinct commit per pull request (squash, merge commit), the same commit for every
pull request, and no commit. The forge returns what it reports; the dispatch records a commit
only when it is on the default branch. Real git in temporary repositories."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.forges.base import PullRequest, RepoId
from agent_build_kit.forges.github import GitHubForge
from agent_build_kit.pipeline import events
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import MERGED, SETTLING
from tests.conftest import make_installation
from tests.factories import commit, git, init_repo, stored_unit
from tests.forges import github_answers
from tests.forges.github_host import GitHubHost

pytestmark = pytest.mark.usefixtures("github_env")

REPO = RepoId(forge="github", account="example", name="app")
MERGED_AT = "2026-10-01T12:00:00Z"
UNIT = "feature/1"
PR = 7


def merged(number: int, commit: str | None) -> dict:
    node = github_answers.pull(number, state="MERGED", merged_at=MERGED_AT, merge_commit=commit)
    if commit is None:
        node["mergeCommit"] = None
    return node


@pytest.mark.parametrize(
    ("reported", "answer"),
    [
        pytest.param({7: "a" * 40, 8: "b" * 40, 9: "c" * 40}, "b" * 40, id="distinct-per-pull"),
        pytest.param(
            {7: "d" * 40, 8: "d" * 40, 9: "d" * 40}, "d" * 40, id="the-same-for-every-pull"
        ),
        pytest.param({7: None, 8: None, 9: None}, None, id="no-commit"),
    ],
)
def test_the_forge_answers_the_commit_it_reports_for_each_pull_request_of_a_stack(
    reported: dict[int, str | None], answer: str | None
) -> None:
    host = GitHubHost(*(merged(number, sha) for number, sha in reported.items()))

    assert GitHubForge(http=host).merge_commit_of(REPO, 8) == answer


class World:
    """An origin and a clone with `main`, a unit settling after its pull request merged, and a
    commit that exists only on a branch beside `main`."""

    def __init__(self, tmp_path: Path) -> None:
        inst = make_installation(tmp_path / "inst")
        origin = tmp_path / "origin.git"
        origin.mkdir()
        git(origin, "init", "-q", "--bare", "-b", "main")
        self.clone = init_repo(inst.checkouts["app"])
        git(self.clone, "remote", "add", "origin", str(origin))
        commit(self.clone, "base")
        git(self.clone, "push", "-q", "origin", "main")
        git(self.clone, "checkout", "-q", "-b", "elsewhere")
        self.off_default = commit(self.clone, "only-on-the-stack-branch")
        git(self.clone, "push", "-q", "origin", "elsewhere")
        git(self.clone, "checkout", "-q", "main")
        self.on_default = commit(self.clone, "squashed-into-main")
        git(self.clone, "push", "-q", "origin", "main")
        self.store = UnitStore(tmp_path / "units.json")
        self.store.upsert([stored_unit(UNIT, change="feature")])
        self.dispatch = events.build_dispatch(
            self.store,
            restack=lambda **k: None,
            merge_record=lambda unit: (unit.merge_sha, None),
            repos={"app": self.clone},
            log=lambda line: None,
        )

    def settling_with(self, sha: str) -> PullRequest:
        """The unit settling on `sha`, and the listing's snapshot of its merged pull request as
        the forge reports it."""
        self.store.set_state(UNIT, SETTLING, pr=PR, branch=f"spec/{UNIT}")
        self.store.set_merge_record(UNIT, sha, None)
        host = GitHubHost(merged(PR, sha))
        [pull] = GitHubForge(http=host).list_prs(REPO)
        return pull

    def settled(self, pull: PullRequest) -> str:
        self.dispatch("settled", PR, repo="app", pull=pull)
        return self.store.get(UNIT).state


def test_a_reported_commit_on_the_default_branch_is_accepted(tmp_path: Path) -> None:
    world = World(tmp_path)

    assert world.settled(world.settling_with(world.on_default)) == MERGED
    assert world.store.get(UNIT).merge_sha == world.on_default


def test_a_reported_commit_that_is_not_on_the_default_branch_is_not_trusted(tmp_path: Path) -> None:
    world = World(tmp_path)

    assert world.settled(world.settling_with(world.off_default)) == SETTLING
