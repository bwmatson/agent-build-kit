"""A restack takes the repository's turn per phase, never while an agent works.

The turn is the real lock file; the agent is a fake resolver that can block on
an event. What it shows is read from outside: another thread's worktree add and
push complete while the resolver is blocked, and every git command that writes
state the repository's worktrees share is made inside the turn.
"""

from __future__ import annotations

import threading
from functools import partial
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline import restack
from agent_build_kit.pipeline.file_lock import file_lock
from agent_build_kit.pipeline.restack import (
    ConflictContext,
    RestackConflict,
    StaleRemote,
    move_branch_onto,
    resolved_move,
)
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import PLANNED
from agent_build_kit.pipeline.wiring import build_restack_onto
from agent_build_kit.runtimes.base import AgentRateLimited
from tests.factories import git, unit
from tests.pipeline.test_restack_onto_before_push import BASE, Repos, stack
from tests.pipeline.test_restack_onto_before_push import BRANCH as UNIT_BRANCH
from tests.restack_turn_fakes import (
    BRANCH,
    OLD_BASE,
    Counting,
    Rig,
    around_the_resolver,
    commit_file,
    conflicting_repo,
    extra_commit,
    keeps_both,
    lock_is_held,
    mark_resolver,
    rebase_in_progress,
    run_bounded,
    sh,
    spy_git,
    writes_shared_state,
)

CONTEXT = ConflictContext(
    moving_unit="c/2",
    moving_intent="Register the local_stack marker",
    onto_unit="c/1",
    onto_intent="Register the integration marker",
)


def move(repo: Path, resolver, turn) -> object:
    return move_branch_onto(
        repo,
        BRANCH,
        new_base="main",
        old_base=OLD_BASE,
        resolve=resolver,
        context=CONTEXT,
        turn=turn,
    )


def test_another_units_worktree_add_and_push_complete_while_the_resolver_is_blocked(
    tmp_path: Path,
) -> None:
    repo = conflicting_repo(tmp_path / "repo")
    remote = tmp_path / "remote.git"
    sh(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "-q", "origin", "main")
    lock = tmp_path / "turn.lock"
    turn = Counting(partial(file_lock, lock))
    at_resolver, release = threading.Event(), threading.Event()

    def blocked(prompt: str, *, cwd: Path) -> None:
        at_resolver.set()
        assert release.wait(60)
        keeps_both(cwd)

    outcome: list[object] = []
    mover = threading.Thread(target=lambda: outcome.append(move(repo, blocked, turn)), daemon=True)
    mover.start()
    assert at_resolver.wait(60)

    other = tmp_path / "other"
    failures: list[BaseException] = []

    def another_unit() -> None:
        try:
            with file_lock(lock):
                sh(repo, "worktree", "add", "-q", "-b", "spec/d/1", str(other), "main")
            (other / "d.py").write_text("D = 1\n")
            sh(other, "add", "-A")
            sh(other, "-c", "user.email=t@t.t", "-c", "user.name=t", "commit", "-qm", "d")
            with file_lock(lock):
                sh(other, "push", "-q", "origin", "spec/d/1")
        except BaseException as error:
            failures.append(error)

    neighbour = threading.Thread(target=another_unit, daemon=True)
    neighbour.start()
    neighbour.join(30)
    finished = not neighbour.is_alive()
    release.set()
    mover.join(timeout=60)

    assert finished, "another unit waited for the agent"
    assert not failures
    assert not mover.is_alive()
    assert [m.resolved for m in outcome] == [("markers.py",)]  # type: ignore[attr-defined]
    assert sh(remote, "rev-parse", "spec/d/1")
    assert turn.taken >= 2, "the rebase's start and its continuation each take the turn"


def test_the_turn_is_held_for_the_rebase_start_and_the_continue_and_not_between(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = conflicting_repo(tmp_path / "repo")
    lock = tmp_path / "turn.lock"
    calls = spy_git(monkeypatch, lock)

    def resolver(prompt: str, *, cwd: Path) -> None:
        mark_resolver(calls, lock, cwd)
        keeps_both(cwd)

    run_bounded(lambda: move(repo, resolver, partial(file_lock, lock)))

    before, during, after = around_the_resolver(calls)
    assert not during.held
    assert any(c.verb[:2] == ("rebase", "--onto") and c.held for c in before)
    assert any(c.verb[:2] == ("rebase", "--continue") and c.held for c in after)
    assert [c.verb for c in calls if writes_shared_state(c) and not c.held] == []


def test_a_clean_move_holds_the_turn_for_its_git_commands_only_and_calls_no_resolver(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = conflicting_repo(tmp_path / "repo")
    git(repo, "checkout", "-q", "-b", "spec/c/3", OLD_BASE)
    commit_file(repo, "extra.py", "EXTRA = 1\n")
    git(repo, "checkout", "-q", "main")
    lock = tmp_path / "turn.lock"
    calls = spy_git(monkeypatch, lock)
    asked: list[str] = []

    moved = run_bounded(
        lambda: move_branch_onto(
            repo,
            "spec/c/3",
            new_base="main",
            old_base=OLD_BASE,
            resolve=lambda prompt, *, cwd: asked.append(prompt),
            context=CONTEXT,
            turn=partial(file_lock, lock),
        )
    )

    assert not moved.resolved  # type: ignore[attr-defined]
    assert asked == []
    assert any(c.verb[0] == "rebase" and c.held for c in calls)
    assert [c.verb for c in calls if writes_shared_state(c) and not c.held] == []
    assert not lock_is_held(lock)


def test_a_rate_limit_aborts_the_rebase_inside_the_turn_and_leaves_the_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = conflicting_repo(tmp_path / "repo")
    old_head = sh(repo, "rev-parse", BRANCH)
    lock = tmp_path / "turn.lock"
    calls = spy_git(monkeypatch, lock)

    def limited(prompt: str, *, cwd: Path) -> None:
        mark_resolver(calls, lock, cwd)
        raise AgentRateLimited("usage window spent")

    with pytest.raises(AgentRateLimited):
        run_bounded(lambda: move(repo, limited, partial(file_lock, lock)))

    _, _, after = around_the_resolver(calls)
    assert any(c.verb[:2] == ("rebase", "--abort") and c.held for c in after)
    assert sh(repo, "rev-parse", BRANCH) == old_head
    assert not rebase_in_progress(repo)


def test_an_error_from_the_resolver_aborts_inside_the_turn_and_is_a_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = conflicting_repo(tmp_path / "repo")
    lock = tmp_path / "turn.lock"
    calls = spy_git(monkeypatch, lock)

    def broken(prompt: str, *, cwd: Path) -> None:
        mark_resolver(calls, lock, cwd)
        raise RuntimeError("the agent crashed")

    with pytest.raises(RestackConflict):
        run_bounded(lambda: move(repo, broken, partial(file_lock, lock)))

    _, _, after = around_the_resolver(calls)
    assert any(c.verb[:2] == ("rebase", "--abort") and c.held for c in after)
    assert not rebase_in_progress(repo)


def test_the_stack_move_handler_takes_the_turn_per_phase_and_not_around_the_move(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = Rig(tmp_path, monkeypatch)
    calls = spy_git(monkeypatch, rig.lock)

    def resolver(request) -> None:
        mark_resolver(calls, rig.lock, request.cwd)
        keeps_both(request.cwd)

    rig.act = resolver

    run_bounded(rig.restack)

    before, during, after = around_the_resolver(calls)
    assert not during.held
    assert any(c.verb[0] == "rebase" and c.held for c in before)
    assert any(c.verb[:2] == ("rebase", "--continue") and c.held for c in after)
    assert [c.verb for c in calls if writes_shared_state(c) and not c.held] == []


def test_a_units_own_restack_in_a_run_takes_the_turn_for_the_same_phases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repos = Repos(tmp_path, edits_shared=True)
    store = stack(tmp_path)
    repos.advance_trunk(conflicting=True)
    lock = tmp_path / "turn.lock"
    calls = spy_git(monkeypatch, lock)

    def resolver(prompt: str, *, cwd: Path) -> None:
        mark_resolver(calls, lock, cwd)
        (cwd / "shared.py").write_text("value = 3\nvalue = 2\n")

    restack_onto = build_restack_onto(
        store,
        move=partial(resolved_move, resolve=resolver),
        turn=partial(file_lock, lock),
    )

    moved = run_bounded(
        lambda: restack_onto(tree=repos.tree, branch=UNIT_BRANCH, base=BASE, unit=unit())
    )

    assert moved is not None and moved.resolved == ("shared.py",)
    before, during, after = around_the_resolver(calls)
    assert not during.held
    assert any(c.verb[:2] == ("rebase", "--onto") and c.held for c in before)
    assert any(c.verb[:2] == ("rebase", "--continue") and c.held for c in after)
    assert [c.verb for c in calls if writes_shared_state(c) and not c.held] == []


def test_a_branch_that_moved_during_the_resolver_is_restacked_again_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = Rig(tmp_path, monkeypatch)
    moved_to = extra_commit(rig.repo, BRANCH, "other.py", tmp_path / "scratch")
    asked: list[str] = []

    def resolver(request) -> None:
        asked.append(sh(rig.repo, "rev-parse", BRANCH))
        if len(asked) == 1:
            sh(rig.repo, "update-ref", f"refs/heads/{BRANCH}", moved_to)
        keeps_both(request.cwd)

    rig.act = resolver

    run_bounded(rig.restack)

    assert len(asked) == 2, "started again from its first phase, once"
    assert asked[1] == moved_to
    sh(rig.repo, "merge-base", "--is-ancestor", "main", BRANCH)
    assert sh(rig.repo, "show", f"{BRANCH}:other.py") == "other.py"


def test_a_branch_that_moved_again_is_held_with_both_heads_and_nothing_is_pushed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = Rig(tmp_path, monkeypatch)
    first = extra_commit(rig.repo, BRANCH, "one.py", tmp_path / "scratch1")
    second = extra_commit(rig.repo, first, "two.py", tmp_path / "scratch2")
    asked: list[int] = []

    def resolver(request) -> None:
        asked.append(len(asked))
        target = first if len(asked) == 1 else second
        sh(rig.repo, "update-ref", f"refs/heads/{BRANCH}", target)
        keeps_both(request.cwd)

    rig.act = resolver

    run_bounded(rig.restack)

    stored = rig.store.get(rig.child.id)
    assert len(asked) == 2, "retried once and no more"
    assert stored.state == PLANNED
    assert stored.cause == Cause.RESTACK_DEFERRED
    assert BRANCH in stored.note
    assert first[:7] in stored.note and second[:7] in stored.note
    assert sh(rig.repo, "rev-parse", BRANCH) == second, "the branch is left as it was moved"
    assert not rig.temporary_tree().exists()


def test_a_remote_that_moved_is_refused_by_the_lease_and_the_move_is_not_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = Rig(tmp_path, monkeypatch)
    rig.use_clean_approved_branch()
    moves: list[str] = []
    pushes: list[str] = []

    def tier1(**kwargs: Any):
        return lambda *, cwd, base, moved_from=None: (True, "")

    def refused(repo: Path, branch: str, *, last_pushed: str | None) -> str:
        pushes.append(branch)
        raise StaleRemote("the remote branch moved since the last push")

    real_move = restack.move_branch_onto

    def counting_move(*args: Any, **kwargs: Any):
        moves.append("move")
        return real_move(*args, **kwargs)

    monkeypatch.setattr(cli, "build_tier1", tier1)
    monkeypatch.setattr(cli, "push_with_lease", refused)
    monkeypatch.setattr(restack, "move_branch_onto", counting_move)

    with pytest.raises(StaleRemote):
        run_bounded(rig.restack)

    assert moves == ["move"], "moved once, and not again for the remote"
    assert pushes == [rig.branch], "pushed once"
