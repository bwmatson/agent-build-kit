"""The move of a branch with no commits that `build_runner` gives a unit's run is the real one,
over a real git repository, and takes the repository's turn (spec: prepare-base)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.wiring import build_move_empty_branch, build_runner
from tests.conftest import make_installation
from tests.empty_branch_support import advance, head
from tests.factories import git, unit
from tests.graph.test_outside_commits_prompt import branch


def test_the_runner_fast_forwards_an_empty_branch_and_gives_the_old_and_new_tips(
    tmp_path: Path,
) -> None:
    repo = branch(tmp_path)
    old = head(repo)
    new = advance(repo)
    installation = make_installation(
        tmp_path / "planning",
        repos={"app": {"path": str(repo), "slug": "example/app"}},
        planning=dict(worktree_root=str(tmp_path / "trees")),
    )
    runner = build_runner(
        unit(),
        store=UnitStore(tmp_path / "units.json"),
        installation=installation,
        log=lambda _: None,
    )

    moved = runner.move_empty_branch(repo, "refs/remotes/origin/main")

    assert moved == (old, new)
    assert head(repo) == new
    assert runner.move_empty_branch(repo, "refs/remotes/origin/main") is None
    assert git(repo, "rev-parse", "HEAD").strip() == new


def test_the_move_happens_inside_the_repos_turn(tmp_path: Path) -> None:
    repo = branch(tmp_path)
    new = advance(repo)
    seen: list[str] = []

    @contextmanager
    def turn() -> Iterator[None]:
        seen.append("enter")
        yield
        seen.append(f"exit with the branch at {'new' if head(repo) == new else 'old'}")

    build_move_empty_branch(turn=turn)(repo, "refs/remotes/origin/main")

    assert seen == ["enter", "exit with the branch at new"]
