"""Several pull requests of a stack merged at once are each settled by their own commit, and a
unit with no commit is held after `landing_wait` (spec: stacked-merge-landing).

Real git in temporary repositories: an origin, a clone, and a stack of three units, each one
commit on the one below. How the forge reports a stack merge is an assumption from its
documentation, not a recording: a squash gives a commit per pull request on the default branch,
a rebase gives no single commit. The clock is the fake one."""

from __future__ import annotations

import itertools
from datetime import timedelta
from pathlib import Path

import pytest

from agent_build_kit.config import active
from agent_build_kit.forges.base import PullRequest
from agent_build_kit.pipeline import events
from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import HELD, IN_REVIEW, MERGED, SETTLING
from tests.conftest import make_installation
from tests.factories import commit_files, git, init_repo, stored_unit
from tests.fake_clock import FakeClock, install

PRS = (1, 2, 3)


def unit_id(pr: int) -> str:
    return f"feature/{pr}"


class Stack:
    """An origin and a clone, a three-unit stack whose unit `n` is one commit on unit `n - 1`,
    and a store holding the three units."""

    def __init__(self, root: Path, *, state=IN_REVIEW) -> None:
        inst = make_installation(root / "inst")
        origin = root / "origin.git"
        origin.mkdir(parents=True)
        git(origin, "init", "-q", "--bare", "-b", "main")
        self.clone = init_repo(inst.checkouts["app"])
        git(self.clone, "remote", "add", "origin", str(origin))
        commit_files(self.clone, "base", {"base.txt": "base\n"})
        git(self.clone, "push", "-q", "origin", "main")
        self.tips: dict[int, str] = {}
        git(self.clone, "checkout", "-q", "-b", "stack")
        for pr in PRS:
            commit_files(self.clone, f"unit {pr}", {f"f{pr}.txt": f"{pr}\n"})
            self.tips[pr] = git(self.clone, "rev-parse", "HEAD")
        git(self.clone, "checkout", "-q", "main")
        self.store = UnitStore(root / "units.json")
        self.store.upsert(
            [
                stored_unit(unit_id(pr), change="feature", depends_on=(unit_id(pr - 1),))
                if pr > 1
                else stored_unit(unit_id(pr), change="feature")
                for pr in PRS
            ]
        )
        for pr in PRS:
            self.store.set_state(unit_id(pr), state, pr=pr, branch=f"spec/{unit_id(pr)}")
            if state == SETTLING:
                self.store.set_merge_record(unit_id(pr), self.tips[pr], None)
        self.dispatch = events.build_dispatch(
            self.store,
            restack=lambda **k: None,
            merge_record=lambda unit: (unit.merge_sha, None),
            repos={"app": self.clone},
            log=lambda _line: None,
        )

    def squash_onto_main(self) -> dict[int, str]:
        """Each unit's work as its own new commit on the default branch, as a squash merge of
        the whole stack leaves it."""
        shas: dict[int, str] = {}
        for pr in PRS:
            commit_files(self.clone, f"squash {pr}", {f"f{pr}.txt": f"{pr}\n"})
            shas[pr] = git(self.clone, "rev-parse", "HEAD")
        git(self.clone, "push", "-q", "origin", "main")
        return shas

    def rebase_onto_main(self) -> str:
        """Each unit's commit replayed on the default branch, as a rebase merge leaves it: new
        commits and no single one for a pull request. The default branch's head."""
        for pr in PRS:
            # A different committer, as the forge's: the replayed commit is never the original.
            git(self.clone, "-c", "user.name=Forge", "cherry-pick", self.tips[pr])
        git(self.clone, "push", "-q", "origin", "main")
        return git(self.clone, "rev-parse", "HEAD")

    def pull(self, pr: int, commit: str | None) -> PullRequest:
        return PullRequest(
            number=pr, head=f"spec/{unit_id(pr)}", base="main", state="merged", merge_commit=commit
        )

    def poll(self, order: tuple[int, ...], commits: dict[int, str | None]) -> None:
        """One round: each merge event in `order`, then each unit's checks settling, then the
        landing re-check."""
        for event in ("merged", "settled"):
            for pr in order:
                self.dispatch(event, pr, repo="app", pull=self.pull(pr, commits.get(pr)))
        self.recheck()

    def settle(self, pr: int) -> None:
        self.dispatch("settled", pr, repo="app", pull=self.pull(pr, None))
        self.recheck()

    def recheck(self) -> None:
        events.recheck_landings(
            self.store,
            repos={"app": self.clone},
            merge_record=lambda unit: (unit.merge_sha, None),
            log=lambda _line: None,
        )


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    return install(monkeypatch)


@pytest.mark.parametrize("order", list(itertools.permutations(PRS)))
def test_a_squashed_stack_with_no_reported_commits_is_settled_in_any_order_of_the_merge_events(
    tmp_path: Path, clock: FakeClock, order: tuple[int, ...]
) -> None:
    stack = Stack(tmp_path, state=SETTLING)
    shas = stack.squash_onto_main()

    stack.poll(order, {})

    landed = {
        pr: (stack.store.get(unit_id(pr)).state, stack.store.get(unit_id(pr)).merge_sha)
        for pr in PRS
    }
    assert landed == {pr: (MERGED, shas[3]) for pr in PRS}


def test_a_rebase_merged_stack_is_settled_from_its_content_with_the_default_branchs_head(
    tmp_path: Path, clock: FakeClock
) -> None:
    stack = Stack(tmp_path, state=SETTLING)
    head = stack.rebase_onto_main()

    stack.poll(PRS, {})

    landed = {
        pr: (stack.store.get(unit_id(pr)).state, stack.store.get(unit_id(pr)).merge_sha)
        for pr in PRS
    }
    assert landed == {pr: (MERGED, head) for pr in PRS}


def test_a_unit_with_no_commit_stays_settling_with_a_deadline_from_landing_wait(
    tmp_path: Path, clock: FakeClock
) -> None:
    stack = Stack(tmp_path, state=SETTLING)

    stack.settle(1)

    unit = stack.store.get(unit_id(1))
    assert unit.state == SETTLING
    assert unit.landing_deadline == clock.now() + timedelta(
        seconds=active().repos["app"].landing_wait
    )


def test_a_unit_with_no_commit_is_held_landing_unknown_naming_the_pull_request_at_the_deadline(
    tmp_path: Path, clock: FakeClock
) -> None:
    stack = Stack(tmp_path, state=SETTLING)
    stack.settle(1)
    clock.advance(active().repos["app"].landing_wait + 1)

    stack.settle(1)

    unit = stack.store.get(unit_id(1))
    assert (unit.state, unit.cause) == (HELD, Cause.LANDING_UNKNOWN)
    assert "#1" in unit.note


def test_a_unit_with_no_commit_is_not_held_before_its_deadline(
    tmp_path: Path, clock: FakeClock
) -> None:
    stack = Stack(tmp_path, state=SETTLING)
    stack.settle(1)
    clock.advance(active().repos["app"].landing_wait - 1)

    stack.settle(1)

    unit = stack.store.get(unit_id(1))
    assert unit.state == SETTLING
    assert unit.landing_deadline is not None


def test_a_commit_that_appears_before_the_deadline_merges_the_unit_and_holds_nothing(
    tmp_path: Path, clock: FakeClock
) -> None:
    stack = Stack(tmp_path, state=SETTLING)
    stack.settle(1)
    clock.advance(active().repos["app"].landing_wait // 2)
    commit_files(stack.clone, "squash 1", {"f1.txt": "1\n"})
    git(stack.clone, "push", "-q", "origin", "main")
    head = git(stack.clone, "rev-parse", "HEAD")

    stack.settle(1)

    unit = stack.store.get(unit_id(1))
    assert (unit.state, unit.merge_sha) == (MERGED, head)
    assert unit.cause != Cause.LANDING_UNKNOWN
