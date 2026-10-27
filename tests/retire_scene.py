"""What the `abk retire` tests share: a planning repo with units in the store, an `app`
checkout with real branches, worktrees and a remote, and a code host that records what it
is asked, registered as the one every repo is on."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from agent_build_kit import forges
from agent_build_kit.cli import main
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.graph.checkpointer import open_checkpointer, unit_graphs_path
from agent_build_kit.graph.state import Node, UnitRun
from agent_build_kit.graph.unit import seed_thread
from agent_build_kit.pipeline.lease import Leases, lease_dir
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import PLANNED, UnitState
from agent_build_kit.pipeline.workspaces import worktree_path
from tests.cli.replan_driver import Replan, tasks_md
from tests.factories import git, init_repo, stored_unit
from tests.forges.stand_in import StandInForge
from tests.review_approval import give_a_remote


class Host(StandInForge):
    """The code host every repo is on."""

    name = "github"


class Scene(Replan):
    """`feature`, a change of three task groups, and `other`, of one, with `app` as their repo."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        super().__init__(tmp_path, monkeypatch, feature=tasks_md(3), other=tasks_md(1))
        self.host = Host()
        forges.register(self.host)
        self.repo = init_repo(self.inst.checkouts["app"])
        (self.repo / "base.txt").write_text("base\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "start")
        self.remote: Path | None = None

    # --- the store ----------------------------------------------------------

    def add(
        self,
        uid: str,
        state: UnitState | str = PLANNED,
        *,
        groups: tuple[int, ...] | None = None,
        change: str = "feature",
        branch: bool = True,
        **fields,
    ) -> StoredUnit:
        """Store the unit as given, in one write that keeps every field, so a group two units
        carry is not refused."""
        extra = {} if groups is None else {"groups": groups}
        record = stored_unit(
            uid,
            change=change,
            state=state,
            branch=f"spec/{uid}" if branch else "",
            **extra,
            **fields,
        )
        self.store.import_units([record])
        return record

    # --- the checkout -------------------------------------------------------

    def commits(self, uid: str, count: int = 1) -> None:
        """The unit's branch, made on `main` when it is not there, with `count` more commits."""
        branch = f"spec/{uid}"
        if not git(self.repo, "branch", "--list", branch).strip():
            git(self.repo, "branch", branch, "main")
        tree = self.worktree(uid) if self.has_worktree(uid) else None
        for number in range(count):
            where = tree or self.repo
            if tree is None:
                git(self.repo, "checkout", "-q", branch)
            name = f"{uid.replace('/', '-')}-{number}-{self.head(uid)[:6]}.txt"
            (where / name).write_text("work\n")
            git(where, "add", "-A")
            git(where, "commit", "-q", "-m", f"work {number}")
            if tree is None:
                git(self.repo, "checkout", "-q", "main")

    def head(self, uid: str) -> str:
        return git(self.repo, "rev-parse", f"spec/{uid}").strip()

    def has_branch(self, uid: str) -> bool:
        return bool(git(self.repo, "branch", "--list", f"spec/{uid}").strip())

    def worktree(self, uid: str) -> Path:
        """The unit's branch checked out where the pipeline keeps it, created when missing."""
        branch = f"spec/{uid}"
        path = worktree_path(self.repo, branch, self.inst.worktree_root, name=self.repo.name)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            git(self.repo, "worktree", "add", "-q", str(path), branch)
        return path

    def has_worktree(self, uid: str) -> bool:
        return worktree_path(
            self.repo, f"spec/{uid}", self.inst.worktree_root, name=self.repo.name
        ).exists()

    def push(self, uid: str) -> str:
        """Push the unit's branch to `origin` and record the commit as the last pushed."""
        if self.remote is None:
            self.remote = give_a_remote(self.repo)
        git(self.repo, "push", "-q", "origin", f"spec/{uid}")
        sha = self.head(uid)
        self.store.record_push(uid, sha)
        return sha

    # --- the rest of what a unit has ----------------------------------------

    def thread(self, uid: str) -> None:
        """A thread for the unit, waiting for review."""

        async def seed() -> None:
            async with open_checkpointer(unit_graphs_path(self.inst.state_dir)) as saver:
                state = UnitRun(unit_id=uid, change="feature")
                await seed_thread(saver, state, as_node=Node.AWAIT_REVIEW)

        asyncio.run(seed())

    def has_thread(self, uid: str) -> bool:
        return cli.has_thread(self.inst, uid)

    def lease(self, uid: str, holder: str = "tab:t1") -> bool:
        """A lease on the unit held by this process, which is alive."""
        return Leases(lease_dir(self.inst.state_dir)).take(uid, holder)

    # --- the command --------------------------------------------------------

    def retire(self, capsys: pytest.CaptureFixture[str], uid: str, *flags: str) -> tuple[int, str]:
        """`abk retire` with its exit code and everything it printed."""
        capsys.readouterr()
        code = main(["retire", uid, *flags])
        seen = capsys.readouterr()
        return code, seen.out + seen.err

    def unit(self, uid: str) -> StoredUnit:
        return self.store.get(uid)

    def snapshot(self) -> tuple[bytes, dict]:
        """The store's bytes and the recorded plans: what a refusal must leave as it was."""
        return self.store.path.read_bytes(), self.records

    def untouched(self) -> bool:
        """Whether the host was asked for nothing that changes anything."""
        host = self.host
        return not (host.closed or host.comments or host.deleted)

    def built_elsewhere(self, uid: str, by: str = "feature/9") -> None:
        """A merged unit that carries the groups of `uid`, so retiring `uid` loses nothing."""
        self.add(by, "merged", groups=self.unit(uid).groups, pr=90)


@pytest.fixture
def scene(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Scene:
    """`feature` of three groups and `other` of one, planned in `tmp_path`."""
    return Scene(tmp_path, monkeypatch)
