"""The assembled runner has `commit_built`, carrying the unit's id (spec:
built-group-recorded-as-empty-pair)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.wiring import build_runner
from tests.factories import commit, git, init_repo, unit
from tests.pipeline.test_unit_account import labelled


def test_the_runner_makes_an_empty_marked_commit_for_its_unit(tmp_path: Path) -> None:
    runner = build_runner(
        unit(),
        store=UnitStore(tmp_path / "units.json"),
        installation=labelled(tmp_path / "planning", None),
        log=lambda _: None,
    )
    tree = init_repo(tmp_path / "tree")
    commit(tree, "base.txt")

    made = runner.commit_built("feat: G4\n\nAlready built.", cwd=tree)

    assert made == 1
    assert git(tree, "show", "--name-only", "--format=", "HEAD") == ""
    assert git(tree, "log", "-1", "--format=%(trailers:key=Unit,valueonly)").strip() == unit().id
    assert (
        git(tree, "log", "-1", "--format=%(trailers:key=Already-built,valueonly)").strip() == "yes"
    )
