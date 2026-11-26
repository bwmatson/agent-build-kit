"""A step that holds a rewrite request leaves the unit's base unchanged (spec:
implement-may-rewrite-its-own-commits). The repositories are real; the agent is a callable that
runs the git commands a rewrite would."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from agent_build_kit.pipeline.restack import push_with_lease
from agent_build_kit.pipeline.rewrite_guard import (
    GuardCheck,
    GuardedStep,
    GuardVerdict,
    guard_rewrite,
    run_guarded_step,
)
from agent_build_kit.pipeline.shell import git, git_out
from agent_build_kit.pipeline.unit_store import RewriteSource, StoredRewriteRequest, UnitStore
from tests.factories import init_repo, unit
from tests.review_repo import commit as review_commit

REQUEST = StoredRewriteRequest(text="fold the support edits into feat", source=RewriteSource.PERSON)
UNIT_ID = "app/1"


def commit(repo: Path, name: str, *, trailer: bool = True) -> str:
    """One commit of a file `name`, with the unit trailer unless `trailer` is false."""
    message = f"work: {name}\n\nUnit: {UNIT_ID}\n" if trailer else f"work: {name}\n"
    return review_commit(repo, name, f"{name}\n", message)


class Scene:
    """A repository on a unit branch: `main` holds the base, the unit has three commits."""

    def __init__(self, repo: Path, *, stacked: bool) -> None:
        self.repo = repo
        commit(repo, "root.txt", trailer=False)
        commit(repo, "base.txt", trailer=False)
        if stacked:
            git(repo, "checkout", "-q", "-b", "parent")
            commit(repo, "parent.txt")
            self.base = "parent"
        else:
            self.base = "main"
        git(repo, "checkout", "-q", "-b", "unit")
        self.base_tip = git_out(repo, "rev-parse", self.base)
        for name in ("a.txt", "b.txt", "c.txt"):
            commit(repo, name)
        self.started = git_out(repo, "rev-parse", "HEAD")

    @property
    def head(self) -> str:
        return git_out(self.repo, "rev-parse", "HEAD")


@pytest.fixture(params=[False, True], ids=["from-main", "stacked"])
def scene(request: pytest.FixtureRequest, tmp_path: Path) -> Scene:
    return Scene(init_repo(tmp_path / "repo"), stacked=request.param)


def fold_three_into_two(scene: Scene) -> None:
    git(scene.repo, "reset", "--soft", scene.base_tip)
    git(scene.repo, "reset", "-q")
    for names in (("a.txt", "b.txt"), ("c.txt",)):
        git(scene.repo, "add", *names)
        git(scene.repo, "commit", "-q", "-m", f"work: {names[0]}\n\nUnit: {UNIT_ID}\n")


def amend_the_base(scene: Scene) -> None:
    git(scene.repo, "reset", "-q", "--soft", scene.base_tip)
    git(scene.repo, "commit", "-q", "--amend", "-m", f"work: all\n\nUnit: {UNIT_ID}\n")


def rewrite_from_below_the_base(scene: Scene) -> None:
    git(scene.repo, "reset", "-q", "--soft", f"{scene.base_tip}~1")
    git(scene.repo, "commit", "-q", "-m", f"work: all\n\nUnit: {UNIT_ID}\n")


def drop_below_the_base(scene: Scene) -> None:
    git(scene.repo, "reset", "-q", "--hard", f"{scene.base_tip}~1")


def amend_then_leave_the_branch(scene: Scene) -> None:
    amend_the_base(scene)
    git(scene.repo, "checkout", "-q", "-b", "other")


def amend_then_raise(scene: Scene) -> None:
    amend_the_base(scene)
    raise RuntimeError("the agent's run was interrupted")


def guarded(scene: Scene, request: StoredRewriteRequest | None = REQUEST) -> GuardVerdict:
    return guard_rewrite(
        scene.repo,
        request=request,
        base=scene.base,
        started_at=scene.started,
        unit_id=UNIT_ID,
    )


def test_a_rewrite_of_the_units_own_commits_with_the_trailer_kept_passes(scene: Scene) -> None:
    fold_three_into_two(scene)
    rewritten = scene.head

    verdict = guarded(scene)

    assert verdict.ok
    assert scene.head == rewritten, "a passing rewrite is left where the agent put it"
    assert git_out(scene.repo, "rev-list", "--count", f"{scene.base_tip}..HEAD") == "2"


@pytest.mark.parametrize(
    "rewrite", [amend_the_base, rewrite_from_below_the_base, drop_below_the_base]
)
def test_a_rewrite_that_reaches_the_base_fails_and_the_branch_goes_back(
    scene: Scene, rewrite: Callable[[Scene], None]
) -> None:
    rewrite(scene)
    assert scene.head != scene.started

    verdict = guarded(scene)

    assert not verdict.ok
    assert verdict.check is GuardCheck.BASE
    assert scene.base in verdict.reason
    assert scene.head == scene.started
    assert git_out(scene.repo, "rev-parse", "unit") == scene.started


def test_a_rebase_of_the_unit_onto_a_changed_base_fails(scene: Scene) -> None:
    git(scene.repo, "checkout", "-q", scene.base)
    commit(scene.repo, "later.txt", trailer=False)
    git(scene.repo, "checkout", "-q", "unit")
    git(scene.repo, "rebase", "-q", scene.base)
    assert scene.head != scene.started

    verdict = guarded(scene)

    assert not verdict.ok
    assert verdict.check is GuardCheck.BASE
    assert scene.head == scene.started


def test_a_commit_with_a_fresh_message_and_no_trailer_fails_naming_the_commit(
    scene: Scene,
) -> None:
    bad = commit(scene.repo, "d.txt", trailer=False)

    verdict = guarded(scene)

    assert not verdict.ok
    assert verdict.check is GuardCheck.TRAILER
    assert bad in verdict.reason
    assert scene.head == scene.started


def test_a_merge_commit_above_the_base_fails_and_the_branch_goes_back(scene: Scene) -> None:
    git(scene.repo, "checkout", "-q", "-b", "side", scene.base_tip)
    side = commit(scene.repo, "side.txt")
    git(scene.repo, "checkout", "-q", "unit")
    git(
        scene.repo,
        "merge",
        "-q",
        "--no-ff",
        "-m",
        f"merge side\n\nUnit: {UNIT_ID}\n",
        side,
    )
    merged = scene.head

    verdict = guarded(scene)

    assert not verdict.ok
    assert verdict.check is GuardCheck.MERGE
    assert merged in verdict.reason
    assert scene.head == scene.started


def test_a_step_that_only_edits_the_working_tree_fails_as_rewriting_nothing_and_leaves_the_edit(
    scene: Scene,
) -> None:
    (scene.repo / "a.txt").write_text("edited\n")

    verdict = guarded(scene)

    assert not verdict.ok
    assert verdict.check is GuardCheck.UNCHANGED
    assert scene.head == scene.started
    assert (scene.repo / "a.txt").read_text() == "edited\n", "left for the agent to fold in"


def test_a_step_that_only_adds_a_commit_on_top_fails_as_rewriting_nothing_and_keeps_it(
    scene: Scene,
) -> None:
    added = commit(scene.repo, "d.txt")

    verdict = guarded(scene)

    assert not verdict.ok
    assert verdict.check is GuardCheck.UNCHANGED
    assert scene.head == added, "the branch is left as it is while returns remain"


@pytest.mark.parametrize("rewrite", [amend_the_base, rewrite_from_below_the_base])
def test_a_step_with_no_request_is_not_checked_by_the_guard(
    scene: Scene, rewrite: Callable[[Scene], None]
) -> None:
    rewrite(scene)
    moved = scene.head

    verdict = guarded(scene, request=None)

    assert verdict.ok
    assert scene.head == moved


class Agent:
    """The agent of a step: each call runs the next action and records what it was told and
    whether the request was still stored."""

    def __init__(self, scene: Scene, store: UnitStore, actions: list[Callable[[Scene], None]]):
        self.scene, self.store, self.actions = scene, store, actions
        self.told: list[str] = []
        self.held: list[bool] = []
        self.seen: list[str] = []  # the head each call found

    def __call__(self, reason: str) -> None:
        self.told.append(reason)
        self.seen.append(self.scene.head)
        self.held.append(self.store.get(UNIT_ID).rewrite_request is not None)
        self.actions[min(len(self.told), len(self.actions)) - 1](self.scene)


@pytest.fixture
def store(tmp_path: Path) -> UnitStore:
    held = UnitStore(tmp_path / "units.json")
    held.upsert([unit(UNIT_ID)])
    held.set_rewrite_request(UNIT_ID, REQUEST)
    return held


def run(scene: Scene, store: UnitStore, agent: Agent, returns: int) -> GuardedStep:
    return run_guarded_step(
        scene.repo,
        request=REQUEST,
        base=scene.base,
        unit_id=UNIT_ID,
        store=store,
        agent=agent,
        returns=returns,
    )


def test_a_failed_guard_is_returned_to_the_agent_inside_the_same_step(
    scene: Scene, store: UnitStore
) -> None:
    agent = Agent(scene, store, [amend_the_base, fold_three_into_two])

    step = run(scene, store, agent, returns=2)

    assert step.ok
    assert step.returned == 1
    assert len(agent.told) == 2
    assert agent.told[0] == ""
    assert scene.base in agent.told[1]
    assert agent.held == [True, True], "the request keeps its permission through the return"


def test_the_unit_fails_after_the_returns_it_already_allows(scene: Scene, store: UnitStore) -> None:
    agent = Agent(scene, store, [amend_the_base])

    step = run(scene, store, agent, returns=2)

    assert not step.ok
    assert step.returned == 2
    assert len(agent.told) == 3
    assert step.verdict.check is GuardCheck.BASE
    assert scene.head == scene.started


@pytest.mark.parametrize("passes", [True, False])
def test_the_request_is_cleared_when_the_step_ends_passed_or_failed(
    scene: Scene, store: UnitStore, passes: bool
) -> None:
    agent = Agent(scene, store, [fold_three_into_two if passes else amend_the_base])

    step = run(scene, store, agent, returns=0)

    assert step.ok is passes
    assert store.get(UNIT_ID).rewrite_request is None


def test_a_refused_branch_is_never_left_for_the_push_to_publish(
    scene: Scene, store: UnitStore
) -> None:
    git(scene.repo, "update-ref", "refs/published/unit", scene.started)
    agent = Agent(scene, store, [amend_the_base])

    step = run(scene, store, agent, returns=1)

    assert not step.ok
    assert git_out(scene.repo, "rev-parse", "unit") == git_out(
        scene.repo, "rev-parse", "refs/published/unit"
    ), "the branch is at the head it was published at, so nothing refused can be pushed"


def test_a_step_that_leaves_the_unit_branch_fails_and_the_branch_is_put_back(
    scene: Scene,
) -> None:
    amend_then_leave_the_branch(scene)

    verdict = guard_rewrite(
        scene.repo,
        request=REQUEST,
        base=scene.base,
        started_at=scene.started,
        unit_id=UNIT_ID,
        branch="unit",
    )

    assert not verdict.ok
    assert verdict.check is GuardCheck.BASE
    assert "unit" in verdict.reason
    assert git_out(scene.repo, "rev-parse", "unit") == scene.started
    assert git_out(scene.repo, "symbolic-ref", "--short", "HEAD") == "unit"


def test_an_agent_that_raises_leaves_the_branch_put_back_and_the_request_cleared(
    scene: Scene, store: UnitStore
) -> None:
    agent = Agent(scene, store, [amend_then_raise])

    with pytest.raises(RuntimeError):
        run(scene, store, agent, returns=1)

    assert git_out(scene.repo, "rev-parse", "unit") == scene.started
    assert store.get(UNIT_ID).rewrite_request is None


def history_events(store: UnitStore) -> list[dict]:
    return [e for e in store.get(UNIT_ID).history if e.get("event") == "history_rewritten"]


def test_a_step_that_rewrote_the_commits_records_in_the_history_who_asked(
    scene: Scene, store: UnitStore
) -> None:
    step = run(scene, store, Agent(scene, store, [fold_three_into_two]), returns=0)

    entries = history_events(store)
    assert step.ok
    assert len(entries) == 1
    assert "person" in entries[0]["note"]
    assert entries[0]["source"] == "person"


def no_commit(scene: Scene) -> None:
    """An agent that leaves the branch where it was."""


def test_a_step_with_a_request_whose_agent_makes_no_commit_fails_and_records_no_rewrite(
    scene: Scene, store: UnitStore
) -> None:
    step = run(scene, store, Agent(scene, store, [no_commit]), returns=0)

    assert not step.ok
    assert step.verdict.check is GuardCheck.UNCHANGED
    assert history_events(store) == []


def test_a_step_with_no_request_records_no_rewrite_however_the_agent_moves_the_branch(
    scene: Scene, store: UnitStore
) -> None:
    run_guarded_step(
        scene.repo,
        request=None,
        base=scene.base,
        unit_id=UNIT_ID,
        store=store,
        agent=lambda _reason: fold_three_into_two(scene),
        returns=0,
    )

    assert history_events(store) == []


def test_a_step_whose_guard_fails_on_every_return_records_no_rewrite(
    scene: Scene, store: UnitStore
) -> None:
    step = run(scene, store, Agent(scene, store, [amend_the_base]), returns=1)

    assert not step.ok
    assert history_events(store) == []


def add_on_top(scene: Scene) -> None:
    commit(scene.repo, f"fixup-{scene.head[:7]}.txt")  # a new file each call, so each commits


def edit_the_tree(scene: Scene) -> None:
    (scene.repo / "a.txt").write_text("edited\n")


def test_a_step_that_added_commits_on_top_is_returned_with_them_kept_until_it_folds(
    scene: Scene, store: UnitStore
) -> None:
    agent = Agent(scene, store, [add_on_top, fold_three_into_two])

    step = run(scene, store, agent, returns=2)

    assert step.ok
    assert step.returned == 1
    assert agent.seen[1] != scene.started, "the second call finds the commit the first made"
    assert "rewr" in agent.told[1].lower()


def test_a_step_that_only_edited_the_tree_is_returned_with_the_edit_in_place(
    scene: Scene, store: UnitStore
) -> None:
    agent = Agent(scene, store, [edit_the_tree, fold_three_into_two])

    step = run(scene, store, agent, returns=2)

    assert step.ok
    assert step.returned == 1
    assert agent.seen[1] == scene.started
    assert "rewr" in agent.told[1].lower()


@pytest.mark.parametrize("act", [add_on_top, edit_the_tree], ids=["commit", "tree-edit"])
def test_a_step_that_rewrites_nothing_on_every_return_ends_at_the_head_it_began_on(
    scene: Scene, store: UnitStore, act: Callable[[Scene], None]
) -> None:
    step = run(scene, store, Agent(scene, store, [act]), returns=1)

    assert not step.ok
    assert step.returned == 1
    assert step.verdict.check is GuardCheck.UNCHANGED
    assert scene.head == scene.started
    assert git_out(scene.repo, "rev-parse", "unit") == scene.started
    assert (scene.repo / "a.txt").read_text() == "a.txt\n"


def kept_ref(scene: Scene) -> str:
    short = git_out(scene.repo, "rev-parse", "--short", scene.started)
    return f"refs/abk/before-rewrite/unit/{short}"


def test_the_head_is_kept_under_a_ref_before_the_step_and_the_history_names_it(
    scene: Scene, store: UnitStore
) -> None:
    held: list[str] = []

    def look(_scene: Scene) -> None:
        found = git(scene.repo, "rev-parse", "-q", "--verify", kept_ref(scene), check=False)
        held.append(found.stdout.strip())
        fold_three_into_two(scene)

    run(scene, store, Agent(scene, store, [look]), returns=0)

    assert held == [scene.started], "the ref points at the head before the agent runs"
    assert git_out(scene.repo, "rev-parse", kept_ref(scene)) == scene.started
    assert kept_ref(scene) in str(store.get(UNIT_ID).history)


def test_the_same_ref_is_used_when_a_killed_step_is_resumed(scene: Scene, store: UnitStore) -> None:
    with pytest.raises(RuntimeError):
        run(scene, store, Agent(scene, store, [amend_then_raise]), returns=1)
    store.set_rewrite_request(UNIT_ID, REQUEST)

    step = run(scene, store, Agent(scene, store, [fold_three_into_two]), returns=0)

    assert step.ok
    refs = git_out(scene.repo, "for-each-ref", "--format=%(refname)", "refs/abk/before-rewrite/")
    assert refs.split() == [kept_ref(scene)]
    named = [e for e in store.get(UNIT_ID).history if e.get("event") == "head_kept"]
    assert len(named) == 1, "the resumed step does not name the same ref twice"


def test_a_push_of_the_branch_does_not_send_the_kept_head(
    scene: Scene, store: UnitStore, tmp_path: Path
) -> None:
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", str(remote))
    git(scene.repo, "remote", "add", "origin", str(remote))
    run(scene, store, Agent(scene, store, [fold_three_into_two]), returns=0)

    push_with_lease(scene.repo, "unit", last_pushed=None)

    kept = git(scene.repo, "rev-parse", "-q", "--verify", kept_ref(scene), check=False)
    assert kept.stdout.strip() == scene.started, "the head is kept locally"
    assert "refs/abk" not in git_out(remote, "for-each-ref")
