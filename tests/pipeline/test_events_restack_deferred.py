"""A child whose branch is checked out where the pipeline does not work, and has no worktree of
its own, is not restacked: the restack is deferred and the checkout is left as it was (spec:
unit-worktrees)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import events
from agent_build_kit.pipeline.events import RestackOutcome
from agent_build_kit.pipeline.restack import Moved
from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import PLANNED
from tests.factories import git, init_repo, stored_unit
from tests.pipeline.test_flake_fix_change import change_with_unit

BRANCH = "spec/feature/1"


def test_a_branch_checked_out_in_the_repos_own_checkout_is_deferred_and_left_alone(
    installation: Installation, tmp_path: Path
) -> None:
    checkout = init_repo(tmp_path / "app")
    (checkout / "README.md").write_text("base\n")
    git(checkout, "add", "-A")
    git(checkout, "commit", "-qm", "base")
    git(checkout, "checkout", "-q", "-b", BRANCH)
    (checkout / "README.md").write_text("unit\n")
    git(checkout, "commit", "-qam", "unit")
    head = git(checkout, "rev-parse", "HEAD")
    child = change_with_unit(installation, "feature", "feature/1").model_copy(
        update={"pr": 2, "branch": BRANCH}
    )
    store = UnitStore(installation.root / "feature.json")
    store.upsert([child])
    moves: list[object] = []

    def move(*args: object, **kwargs: object) -> Moved:
        moves.append(kwargs)
        return Moved(sha="moved")

    restack = events.build_restack(
        repos={"app": checkout},
        store=store,
        root=tmp_path / "trees",
        move=move,
        retarget=lambda *a, **k: None,
        comment=lambda *a, **k: None,
        diff_id=lambda repo, base, branch: "diff",
        head_of=lambda repo, branch: head,
        remote_head_of=lambda repo, branch: None,
    )

    outcome = restack(
        branch=BRANCH,
        old_base="spec/parent/1",
        new_base="main",
        child=child,
        parent=stored_unit("parent/1", change="parent", pr=1, branch="spec/parent/1"),
    )

    left = store.get("feature/1")
    assert outcome is RestackOutcome.DEFERRED
    assert (left.state, left.cause) == (PLANNED, Cause.RESTACK_DEFERRED)
    assert BRANCH in left.note
    assert str(checkout) in left.note
    assert moves == [], "nothing was moved"
    assert git(checkout, "branch", "--show-current") == BRANCH
    assert git(checkout, "rev-parse", "HEAD") == head
    assert (checkout / "README.md").read_text() == "unit\n"
    assert "restack-" not in git(checkout, "worktree", "list", "--porcelain")
