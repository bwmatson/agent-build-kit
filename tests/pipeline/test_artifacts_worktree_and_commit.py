"""The artifacts an environment names are the pipeline's: the worktree check ignores them, the
commit step never stages them, and a move of the branch keeps them; a tracked file under an
artifact pattern is ordinary work (spec: pipeline-environment). Real git throughout.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.config import RepoConfig
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.wiring import build_commit, build_restack_onto, build_worktree
from agent_build_kit.pipeline.workspaces import DirtyWorktree
from tests.environment_fakes import FakeEnvironment, repo_config
from tests.factories import git, init_repo, unit

MANIFEST = "manifest.toml"
LOCK = "deps.lock"
BRANCH = "spec/add-marker/1"
SHAPES = [pytest.param(".venv", id="python-shaped"), pytest.param("modules", id="node-shaped")]


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    work = init_repo(tmp_path / "repo")
    (work / "README.md").write_text("base\n")
    (work / MANIFEST).write_text('widget = "1"\n')
    (work / LOCK).write_text("as committed\n")
    git(work, "add", "-A")
    git(work, "commit", "-qm", "base")
    return work


def configured(tmp_path: Path, *artifacts: str) -> RepoConfig:
    env = FakeEnvironment(
        tmp_path / "control", inputs=(MANIFEST,), locks=(LOCK,), artifacts=artifacts
    )
    return repo_config(tmp_path / "meta", env)


def fill(tree: Path, artifact: str) -> None:
    """What a sync leaves in `artifact`: a package with a manifest and a built file."""
    package = tree / artifact / "pkg"
    package.mkdir(parents=True)
    (package / "manifest.json").write_text("{}\n")
    (package / "built.bin").write_text("built\n")


def worktree_of(repo: Path, tmp_path: Path, config: RepoConfig) -> Path:
    return build_worktree({"app": repo}, root=tmp_path / "trees", repo=config)(unit(), "main")


def held_by(work: Path, tmp_path: Path, config: RepoConfig, *, filling: str) -> list[str] | None:
    """What holds the unit's worktree once the sync filled `filling`, asked for through
    `build_worktree` as a unit's steps do; None when nothing does."""
    worktree = build_worktree({"app": work}, root=tmp_path / "trees", repo=config)
    fill(worktree(unit(), "main"), filling)
    try:
        worktree(unit(), "main")
    except DirtyWorktree as dirty:
        return sorted(dirty.paths)
    return None


@pytest.mark.parametrize("artifact", SHAPES)
def test_an_artifact_folder_the_repository_does_not_ignore_does_not_hold_the_worktree(
    repo: Path, tmp_path: Path, artifact: str
) -> None:
    config = configured(tmp_path, artifact)

    assert held_by(repo, tmp_path, config, filling=artifact) is None
    assert any((tmp_path / "trees").rglob("built.bin")), "and it is still there"


def test_another_uncommitted_file_still_holds_a_worktree_and_is_the_only_path_named(
    repo: Path, tmp_path: Path
) -> None:
    config = configured(tmp_path, "modules")
    worktree = build_worktree({"app": repo}, root=tmp_path / "trees", repo=config)
    tree = worktree(unit(), "main")
    fill(tree, "modules")
    (tree / "stray.txt").write_text("mine\n")

    with pytest.raises(DirtyWorktree) as dirty:
        worktree(unit(), "main")

    assert sorted(dirty.value.paths) == ["stray.txt"]
    assert "modules" not in str(dirty.value), "the message does not list the artifact either"


def test_without_artifacts_the_same_folder_holds_the_worktree(repo: Path, tmp_path: Path) -> None:
    held = held_by(repo, tmp_path, configured(tmp_path), filling="modules")

    assert held == ["modules/pkg/built.bin", "modules/pkg/manifest.json"]


def test_a_pattern_with_a_double_star_owns_the_folders_it_matches(
    repo: Path, tmp_path: Path
) -> None:
    config = configured(tmp_path, "**/build")

    assert held_by(repo, tmp_path, config, filling="packages/api/build") is None


def test_an_artifact_pattern_does_not_hide_a_sibling_that_only_shares_its_prefix(
    repo: Path, tmp_path: Path
) -> None:
    config = configured(tmp_path, "modules")

    assert held_by(repo, tmp_path, config, filling="modules-extra") == [
        "modules-extra/pkg/built.bin",
        "modules-extra/pkg/manifest.json",
    ]


# --- the commit step ---------------------------------------------------------------------


def committed_files(tree: Path) -> list[str]:
    return git(tree, "show", "--name-only", "--format=", "HEAD").split()


def commit(tree: Path, config: RepoConfig) -> None:
    made = build_commit(unit_id=unit().id, repo=config, base="main")("feat: the work", cwd=tree)
    assert made == 1


@pytest.mark.parametrize("artifact", SHAPES)
def test_artifacts_are_not_committed_even_when_the_unit_changed_a_dependency_input(
    repo: Path, tmp_path: Path, artifact: str
) -> None:
    config = configured(tmp_path, artifact)
    tree = worktree_of(repo, tmp_path, config)
    (tree / MANIFEST).write_text('widget = "9"\n')
    (tree / LOCK).write_text("resolved for 9\n")
    fill(tree, artifact)

    commit(tree, config)

    assert sorted(committed_files(tree)) == [LOCK, MANIFEST]
    assert (tree / artifact / "pkg" / "built.bin").exists(), "the folder stays in the worktree"


def test_a_staged_artifact_is_taken_out_of_the_commit(repo: Path, tmp_path: Path) -> None:
    config = configured(tmp_path, "modules")
    tree = worktree_of(repo, tmp_path, config)
    (tree / "marker.py").write_text("MARKER = 1\n")
    fill(tree, "modules")
    git(tree, "add", "-A")

    commit(tree, config)

    assert committed_files(tree) == ["marker.py"]
    assert (tree / "modules" / "pkg" / "built.bin").exists()


def test_a_repository_with_no_artifacts_commits_every_change_as_before(
    repo: Path, tmp_path: Path
) -> None:
    config = configured(tmp_path)
    tree = worktree_of(repo, tmp_path, config)
    (tree / "marker.py").write_text("MARKER = 1\n")
    fill(tree, "modules")

    commit(tree, config)

    assert sorted(committed_files(tree)) == [
        "marker.py",
        "modules/pkg/built.bin",
        "modules/pkg/manifest.json",
    ]


# --- a tracked file under an artifact pattern ---------------------------------------------


@pytest.fixture
def vendored(tmp_path: Path) -> Path:
    work = init_repo(tmp_path / "vendored")
    (work / "README.md").write_text("base\n")
    (work / MANIFEST).write_text('widget = "1"\n')
    (work / "vendor").mkdir()
    (work / "vendor" / "lib.txt").write_text("as committed\n")
    git(work, "add", "-A")
    git(work, "commit", "-qm", "base")
    return work


def test_a_tracked_file_under_an_artifact_pattern_is_committed_as_ordinary_work(
    vendored: Path, tmp_path: Path
) -> None:
    config = configured(tmp_path, "vendor")
    tree = worktree_of(vendored, tmp_path, config)
    (tree / "vendor" / "lib.txt").write_text("changed by the unit\n")
    (tree / "vendor" / "new.txt").write_text("an untracked sibling\n")

    commit(tree, config)

    assert committed_files(tree) == ["vendor/lib.txt"], "the untracked sibling is an artifact"
    assert git(tree, "show", "HEAD:vendor/lib.txt").strip() == "changed by the unit"


def test_a_modified_tracked_file_under_an_artifact_pattern_holds_the_worktree(
    vendored: Path, tmp_path: Path
) -> None:
    config = configured(tmp_path, "vendor")
    worktree = build_worktree({"app": vendored}, root=tmp_path / "trees", repo=config)
    tree = worktree(unit(), "main")
    (tree / "vendor" / "lib.txt").write_text("changed by someone\n")

    with pytest.raises(DirtyWorktree) as dirty:
        worktree(unit(), "main")

    assert dirty.value.paths == ("vendor/lib.txt",)


# --- a move of the branch ------------------------------------------------------------------


@pytest.mark.parametrize("artifact", SHAPES)
def test_a_restack_keeps_the_artifacts_the_sync_built(
    repo: Path, tmp_path: Path, artifact: str
) -> None:
    config = configured(tmp_path, artifact)
    tree = worktree_of(repo, tmp_path, config)
    (tree / "marker.py").write_text("MARKER = 1\n")
    git(tree, "add", "-A")
    git(tree, "commit", "-qm", "the unit's work")
    (repo / "trunk.py").write_text("TRUNK = 1\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "trunk advances")
    fill(tree, artifact)
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])

    moved = build_restack_onto(store, repo=config)(
        tree=tree, branch=BRANCH, base="main", unit=unit(), resolve=False
    )

    assert moved is not None and not moved.conflict
    assert git(tree, "rev-parse", "HEAD^") == git(repo, "rev-parse", "main")
    assert (tree / artifact / "pkg" / "built.bin").read_text() == "built\n"
