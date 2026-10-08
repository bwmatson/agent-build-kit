"""The move a unit makes onto its base, with real git: at the start of a run,
and before a push.

`wiring.build_restack_onto` is the real mover, with a resolver double standing
in for the agent and nothing else faked. The push-gate cases run it through
`UnitRunner.run`, with only the agent calls, tier 1, the push and the pull
request faked, so the moved commit is what the gate meets.
"""

from __future__ import annotations

from functools import partial
from pathlib import Path

from agent_build_kit.pipeline.restack import resolved_move
from agent_build_kit.pipeline.stack_runner import UnitRunner
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import PLANNED, local_ref
from agent_build_kit.pipeline.wiring import branch_commits, build_restack_onto
from tests.factories import git, init_repo, unit
from tests.graph_driver import run_on_graph
from tests.pipeline.test_stack_runner import Recorder, make_runner

BRANCH = "spec/add-marker/1"
BASE = local_ref("main")


class Resolver:
    """The conflict resolver: records its calls, then writes what it is told."""

    def __init__(self, writes: dict[str, str] | None = None) -> None:
        self.writes = writes or {}
        self.calls: list[str] = []

    def __call__(self, prompt: str, *, cwd: Path) -> None:
        self.calls.append(prompt)
        for name, text in self.writes.items():
            (cwd / name).write_text(text)


class Repos:
    """A remote, the clone a unit builds in (on its branch, one commit ahead
    of the trunk) and a second clone standing for whoever advances the trunk."""

    def __init__(self, tmp_path: Path, *, edits_shared: bool) -> None:
        remote = tmp_path / "remote.git"
        git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
        self.other = init_repo(tmp_path / "other")
        git(self.other, "remote", "add", "origin", str(remote))
        (self.other / "shared.py").write_text("value = 1\n")
        self.commit(self.other, "first")
        git(self.other, "push", "-q", "origin", "main")

        self.tree = tmp_path / "tree"
        git(tmp_path, "clone", "-q", str(remote), str(self.tree))
        git(self.tree, "config", "user.email", "t@t.t")
        git(self.tree, "config", "user.name", "t")
        git(self.tree, "checkout", "-q", "-b", BRANCH)
        if edits_shared:
            (self.tree / "shared.py").write_text("value = 2\n")
        else:
            (self.tree / "marker.py").write_text("MARKER = 1\n")
        self.commit(self.tree, "the unit's work")

    @staticmethod
    def commit(repo: Path, message: str) -> None:
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", message)

    def head(self) -> str:
        return git(self.tree, "rev-parse", "HEAD")

    def advance_trunk(self, *, conflicting: bool) -> None:
        """A commit on the remote trunk, fetched into the unit's clone."""
        if conflicting:
            (self.other / "shared.py").write_text("value = 3\n")
        else:
            (self.other / "trunk.py").write_text("TRUNK = 1\n")
        self.commit(self.other, "trunk advances")
        git(self.other, "push", "-q", "origin", "main")
        git(self.tree, "fetch", "-q", "origin")

    def rebase_in_progress(self) -> bool:
        return any(
            (self.tree / git(self.tree, "rev-parse", "--git-path", name)).exists()
            for name in ("rebase-merge", "rebase-apply")
        )


def stack(tmp_path: Path) -> UnitStore:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    return store


def mover(store: UnitStore, resolver: Resolver):
    return build_restack_onto(store, move=partial(resolved_move, resolve=resolver))


def test_a_clean_move_puts_the_branch_on_the_new_trunk_and_carries_the_approval(
    tmp_path: Path,
) -> None:
    repos = Repos(tmp_path, edits_shared=False)
    store = stack(tmp_path)
    store.record_approval(unit().id, repos.head())
    repos.advance_trunk(conflicting=False)
    resolver = Resolver()

    moved = mover(store, resolver)(
        tree=repos.tree, branch=BRANCH, base=BASE, unit=unit(), resolve=False
    )

    assert moved is not None and not moved.resolved and not moved.conflict
    assert git(repos.tree, "rev-parse", "HEAD^") == git(repos.tree, "rev-parse", BASE)
    assert store.get(unit().id).approved == repos.head(), "the review still stands: same diff"
    assert resolver.calls == []


def test_a_move_whose_replay_changes_the_diff_does_not_carry_the_approval(
    tmp_path: Path,
) -> None:
    repos = Repos(tmp_path, edits_shared=True)
    store = stack(tmp_path)
    approved = repos.head()
    store.record_approval(unit().id, approved)
    repos.advance_trunk(conflicting=True)
    resolver = Resolver({"shared.py": "value = 3\nvalue = 2\n"})

    moved = mover(store, resolver)(tree=repos.tree, branch=BRANCH, base=BASE, unit=unit())

    assert moved is not None and moved.resolved == ("shared.py",)
    assert len(resolver.calls) == 1
    assert store.get(unit().id).approved == approved, (
        "not the resolved commit: review has not seen it"
    )
    assert repos.head() != approved


def test_a_conflict_without_a_resolver_leaves_the_branch_where_it_was(tmp_path: Path) -> None:
    repos = Repos(tmp_path, edits_shared=True)
    store = stack(tmp_path)
    before = repos.head()
    store.record_approval(unit().id, before)
    repos.advance_trunk(conflicting=True)
    resolver = Resolver({"shared.py": "value = 3\nvalue = 2\n"})

    moved = mover(store, resolver)(
        tree=repos.tree, branch=BRANCH, base=BASE, unit=unit(), resolve=False
    )

    assert moved is not None and moved.conflict
    assert resolver.calls == []
    assert repos.head() == before
    assert not repos.rebase_in_progress()
    assert store.get(unit().id).approved == before


def test_a_branch_already_on_its_base_is_neither_rewritten_nor_reapproved(tmp_path: Path) -> None:
    repos = Repos(tmp_path, edits_shared=False)
    store = stack(tmp_path)
    before = repos.head()
    store.record_approval(unit().id, before)
    resolver = Resolver()

    moved = mover(store, resolver)(
        tree=repos.tree, branch=BRANCH, base=BASE, unit=unit(), resolve=False
    )

    assert moved is None
    assert repos.head() == before
    assert store.get(unit().id).approved == before
    assert resolver.calls == []


class Run:
    """`UnitRunner.run` over a real repository, the trunk advancing when the
    run fetches just before its push (the second fetch)."""

    def __init__(self, tmp_path: Path, *, conflicting: bool) -> None:
        self.repos = Repos(tmp_path, edits_shared=conflicting)
        self.conflicting = conflicting
        self.store = stack(tmp_path)
        self.recorder = Recorder()
        self.resolver = Resolver({"shared.py": "value = 3\nvalue = 2\n"})
        self.fetches = 0
        self.pushed: list[str] = []
        self.before = self.repos.head()
        self.store.record_approval(unit().id, self.before)
        self.store.set_state(unit().id, PLANNED)
        runner = make_runner(self.store, self.recorder, tmp_path)
        runner.worktree = lambda unit, base, allow_dirty=False: self.repos.tree
        runner.branch_commits = branch_commits
        runner.head = lambda tree: git(tree, "rev-parse", "HEAD")
        runner.restack_onto = mover(self.store, self.resolver)
        runner.fetch = self.fetch
        runner.push = self.push
        self.runner: UnitRunner = runner

    def fetch(self, unit) -> None:
        self.fetches += 1
        if self.fetches == 2:
            self.repos.advance_trunk(conflicting=self.conflicting)

    def push(self, branch: str, *, cwd: Path) -> str:
        self.recorder.events.append("push")
        sha = git(cwd, "rev-parse", "HEAD")
        self.pushed.append(sha)
        return sha

    def run(self):
        return run_on_graph(self.runner, self.store.get(unit().id), base="main")
