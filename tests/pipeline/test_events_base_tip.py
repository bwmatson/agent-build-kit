"""The base tip and the fork point a conflict event reads, over a real repository.

A trunk-based unit's base is the trunk's remote ref; a stacked unit's is its parent's branch,
which moves while the trunk does not.
"""

import subprocess
from pathlib import Path

from agent_build_kit.pipeline.events import build_base_tip, build_fork_point
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, branch_name
from tests.factories import git, init_repo, new_unit

PARENT = new_unit("parent/1", repo="app")
CHILD = new_unit("child/1", repo="app", depends_on=("parent/1",))
TRUNK_BASED = new_unit("solo/1", repo="app")


def commit(repo: Path, name: str) -> str:
    (repo / name).write_text(f"{name}\n")
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", f"add {name}")
    return git(repo, "rev-parse", "HEAD")


def repository(tmp_path: Path) -> Path:
    """`main` pushed to an origin, a parent branch and a trunk-based branch cut from it."""
    repo = init_repo(tmp_path / "app")
    commit(repo, "base.txt")
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    git(repo, "remote", "add", "origin", str(origin))
    git(repo, "push", "-q", "origin", "main")
    for unit in (PARENT, TRUNK_BASED):
        git(repo, "checkout", "-q", "-b", branch_name(unit), "main")
        commit(repo, f"{unit.change}.txt")
    git(repo, "checkout", "-q", "main")
    return repo


def store_of(tmp_path: Path) -> UnitStore:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([PARENT, CHILD, TRUNK_BASED])
    store.set_state(PARENT.id, IN_REVIEW, pr=3, branch=branch_name(PARENT))
    return store


def test_a_trunk_based_units_base_tip_is_the_trunks_remote_commit(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    store = store_of(tmp_path)

    tip = build_base_tip(store, {"app": repo})(store.get(TRUNK_BASED.id))

    assert tip == git(repo, "rev-parse", "origin/main")


def test_a_stacked_units_base_tip_is_its_parents_branch_and_moves_with_it(
    tmp_path: Path,
) -> None:
    repo = repository(tmp_path)
    store = store_of(tmp_path)
    base_tip = build_base_tip(store, {"app": repo})
    before = base_tip(store.get(CHILD.id))
    trunk = git(repo, "rev-parse", "origin/main")

    assert before == git(repo, "rev-parse", branch_name(PARENT))
    git(repo, "checkout", "-q", branch_name(PARENT))
    commit(repo, "more.txt")

    after = base_tip(store.get(CHILD.id))
    assert after == git(repo, "rev-parse", branch_name(PARENT))
    assert after != before
    assert git(repo, "rev-parse", "origin/main") == trunk


def test_the_fork_point_is_the_commit_the_branch_sits_on_not_the_trunks_new_tip(
    tmp_path: Path,
) -> None:
    repo = repository(tmp_path)
    store = store_of(tmp_path)
    forked_from = git(repo, "rev-parse", "main")
    git(repo, "checkout", "-q", "main")
    commit(repo, "trunk-moved.txt")
    git(repo, "push", "-q", "origin", "main")

    fork = build_fork_point({"app": repo})(store.get(TRUNK_BASED.id))

    assert fork == forked_from
    assert fork != git(repo, "rev-parse", "origin/main")
