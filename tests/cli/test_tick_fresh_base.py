"""A unit about to push learns from the forge that its parent merged.

Driven through `cmd_tick` with the real merge handler behind `record_merge`: the
forge reports the parent's pull request merged, the store does not, and the
child's own build holds its branch lock while it asks.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.forges.base import PullRequest
from agent_build_kit.pipeline.stack_runner import UnitRunner
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, MERGED
from agent_build_kit.pipeline.wiring import (
    build_base_moved,
    build_fresh_base,
    build_upstream_incomplete,
)
from tests.cli.test_tick_scheduling import isolated, stored, tick, workspace  # noqa: F401
from tests.forges.stand_in import StandInForge, lookup


def test_a_parent_merged_on_the_forge_but_not_in_the_store_is_recorded_during_the_childs_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = workspace(tmp_path)
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored("chain/1"), stored("chain/2", depends_on=("chain/1",))])
    store.set_state("chain/1", IN_REVIEW, pr=7, branch="spec/chain/1")
    forge = StandInForge(
        prs=[PullRequest(number=7, head="spec/chain/1", base="main", state=MERGED)], number=21
    )

    retargeted: list[tuple[str, str]] = []
    removed: list[str] = []
    deleted: list[str] = []
    opened: list[tuple[str, str]] = []
    moved_onto: list[str] = []
    made = [0]
    monkeypatch.setattr(
        cli, "build_restack", lambda **kw: lambda **a: pytest.fail("restacked a tree in use")
    )
    monkeypatch.setattr(
        cli, "build_retarget", lambda: lambda unit, base: retargeted.append((unit.id, base))
    )
    monkeypatch.setattr(
        cli, "build_remove_worktree", lambda *a, **k: lambda repo, branch: removed.append(branch)
    )
    monkeypatch.setattr(
        cli, "build_delete_branch", lambda *a, **k: lambda repo, branch: deleted.append(branch)
    )

    def runner(unit, *, store: UnitStore, installation, record_merge, log, **kwargs) -> UnitRunner:
        def commit(message: str, *, cwd: Path) -> int:
            made[0] += 1
            return 1

        def open_pr(u, *, body: str, base: str, cwd: Path, **bodies: str) -> int:
            opened.append((u.id, base))
            return 21

        return UnitRunner(
            store=store,
            planning_repo=tmp_path / "planning",
            worktree=lambda u, base: tmp_path / "trees" / u.id,
            may_start=lambda: (True, ""),
            run_claude=lambda prompt, *, cwd: "",
            run_rework=lambda prompt, *, cwd: "",
            run_review=lambda *, cwd, context="": '{"approved": true}',
            run_rework_review=lambda *, cwd, context="": '{"approved": true}',
            commit=commit,
            branch_commits=lambda tree, ref: made[0],
            head=lambda tree: f"sha-{made[0]}",
            upstream_incomplete=build_upstream_incomplete(store),
            base_moved=build_base_moved(store),
            restack_onto=lambda *, tree, branch, base, unit, resolve=True: moved_onto.append(base),
            run_tier1=lambda *, cwd, base, whole_repo=False: (True, ""),
            run_tier2=lambda *, cwd: (True, ""),
            push=lambda branch, *, cwd: "pushed",
            open_pr=open_pr,
            post_status=lambda sha, ok: None,
            fresh_base=build_fresh_base(store, for_repo=lookup(forge), record_merge=record_merge),
        )

    monkeypatch.setattr(cli, "build_runner", runner)

    assert tick(inst) == 0

    assert store.get("chain/1").state == MERGED
    assert retargeted == [("chain/2", "main")], "its build holds its branch: only the PR moves"
    assert removed == ["spec/chain/1"]
    assert deleted == [], "the branch stays while the child's build is on it"
    assert opened == [("chain/2", "main")]
    assert moved_onto and moved_onto[-1].endswith("main")
    assert store.get("chain/2").state == IN_REVIEW
