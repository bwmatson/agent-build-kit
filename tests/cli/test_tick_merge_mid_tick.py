"""A merge seen during a tick reaches the dependent only in a later tick whose code has it
(spec: needs-can-wait-for-a-merge). The poll is the real one over a fake poller that reports the
merge; the forge answers the merge commit; the kit's checkout is a throwaway git repository."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.forges.github import GitHubForge
from agent_build_kit.pipeline.stack_runner import RunOutcome, RunStatus
from agent_build_kit.pipeline.units import IN_REVIEW, MERGED, PLANNED
from tests.factories import commit, git, new_unit
from tests.kit_checkout import kit_at
from tests.tick_driver import Setup, make_setup

pytestmark = pytest.mark.usefixtures("scripted_engine")

PARENT = "parent/1"
DEPENDENT = "dependent/1"


class Mid:
    """A parent in review, a dependent with a merge `Needs:` on it, and a kit checkout whose
    head lacks the parent's merge commit, which sits on another branch."""

    def __init__(self, setup: Setup, patch: pytest.MonkeyPatch) -> None:
        self.setup, self.store = setup, setup.store
        self.checkout = setup.inst.checkouts["app"]
        kit_at(self.checkout, patch)
        git(self.checkout, "checkout", "-q", "-b", "merge-commit")
        self.merge_sha = commit(self.checkout, "merged.txt")
        git(self.checkout, "checkout", "-q", "main")
        self.started: list[str] = []
        self.merge_commit_asked: list[int] = []

        self.store.upsert([new_unit(PARENT), new_unit(DEPENDENT, depends_on=(PARENT,))])
        self.store.set_state(PARENT, IN_REVIEW, pr=7, branch=f"spec/{PARENT}")
        self.store.set_needs(DEPENDENT, (PARENT,))
        self.store.set_merge_needs(DEPENDENT, (PARENT,))

        def merge_commit(forge: GitHubForge, repo: Any, pr: int) -> str:
            self.merge_commit_asked.append(pr)
            return self.merge_sha

        def build(unit: Any, **kwargs: Any) -> Any:
            return SimpleNamespace(run=lambda unit, *, base, graph: self.run(unit))

        patch.setattr(GitHubForge, "merge_commit", merge_commit)
        patch.setattr(cli, "build_runner", build)
        # Every poll finds the parent's pull request merged; one that finds it recorded
        # does nothing.
        patch.setattr(cli, "poll_all", lambda inst, **kw: setup.poll(("merged", {}), pr=7))

    def run(self, unit: Any) -> RunOutcome:
        self.started.append(unit.id)
        self.store.set_state(unit.id, IN_REVIEW, pr=20 + len(self.started))
        return RunOutcome(status=RunStatus("open"), detail=f"open {unit.id}", pr=20)

    def fast_forward(self) -> None:
        git(self.checkout, "merge", "-q", "--ff-only", "merge-commit")


@pytest.fixture
def mid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Mid:
    return Mid(make_setup(tmp_path, monkeypatch), monkeypatch)


def test_the_tick_that_sees_the_merge_does_not_start_the_dependent(mid: Mid) -> None:
    mid.setup.tick()

    assert mid.store.get(PARENT).state == MERGED
    assert DEPENDENT not in mid.started
    assert mid.store.get(DEPENDENT).state == PLANNED


def test_the_next_tick_whose_head_has_the_merge_commit_starts_it(mid: Mid) -> None:
    mid.setup.tick()
    assert DEPENDENT not in mid.started
    mid.fast_forward()

    mid.setup.tick()

    assert DEPENDENT in mid.started
    assert mid.store.get(DEPENDENT).state == IN_REVIEW


def test_a_checkout_not_fast_forwarded_leaves_it_planned_and_unconsumed(mid: Mid) -> None:
    mid.setup.tick()
    before = mid.store.get(DEPENDENT)

    mid.setup.tick()

    after = mid.store.get(DEPENDENT)
    assert DEPENDENT not in mid.started
    assert after.state == PLANNED, "not failed and not started"
    assert (after.cause, after.feedback, after.branch) == (
        before.cause,
        before.feedback,
        before.branch,
    ), "nothing of the unit is consumed"


def test_the_poll_records_the_merge_commit_and_tick_once(mid: Mid) -> None:
    mid.setup.tick()
    first = mid.store.get(PARENT)

    mid.fast_forward()
    mid.setup.tick()

    after = mid.store.get(PARENT)
    assert (first.merge_sha, first.merged_tick) == (mid.merge_sha, 1)
    assert (after.merge_sha, after.merged_tick) == (mid.merge_sha, 1)
    assert mid.merge_commit_asked == [7], "the forge is asked once, on the merge"
