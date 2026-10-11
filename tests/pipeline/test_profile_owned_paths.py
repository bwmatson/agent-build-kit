"""The paths a toolchain profile names are the pipeline's own, with or without an environment
section: the worktree check ignores them, the commit step never stages an untracked one, and a
move of the branch restores a tracked one only where an environment can say it is unchanged
(spec: pipeline-environment). Real git throughout; the profiles are the fakes of
`tests/created_files_fakes.py`.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_build_kit.config import ProjectConfig, RepoConfig
from agent_build_kit.pipeline.environment import Ownership, owned_paths
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.wiring import build_commit, build_restack_onto, build_worktree
from agent_build_kit.pipeline.workspaces import DirtyWorktree
from tests.created_files_fakes import (
    LOCK,
    MAKES_LOCK,
    MAKES_NESTED,
    MAKES_NOTHING,
    NESTED,
    Creates,
    Hookless,
    configured,
    registered,
)
from tests.environment_fakes import FakeEnvironment
from tests.factories import git, init_repo, unit

MANIFEST = "manifest.toml"
BRANCH = "spec/add-marker/1"


@pytest.fixture(autouse=True)
def profiles_registered() -> Iterator[None]:
    with registered():
        yield


def repository(root: Path, *tracked: str) -> Path:
    work = init_repo(root)
    (work / "README.md").write_text("base\n")
    (work / MANIFEST).write_text('widget = "1"\n')
    for name in tracked:
        (work / name).parent.mkdir(parents=True, exist_ok=True)
        (work / name).write_text("as committed\n")
    git(work, "add", "-A")
    git(work, "commit", "-qm", "base")
    return work


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return repository(tmp_path / "repo")


@pytest.fixture
def tracking(tmp_path: Path) -> Path:
    return repository(tmp_path / "tracking", LOCK)


def with_environment(tmp_path: Path, profile: str) -> RepoConfig:
    """A repository whose environment declares the manifest as its dependency input."""
    env = FakeEnvironment(tmp_path / "control", inputs=(MANIFEST,))
    return configured(tmp_path / "meta", profile, env)


def without_environment(tmp_path: Path, profile: str) -> RepoConfig:
    return configured(tmp_path / "meta", profile)


def worktree_of(repo: Path, tmp_path: Path, config: RepoConfig) -> Path:
    return build_worktree({"app": repo}, root=tmp_path / "trees", repo=config)(unit(), "main")


def held_by(
    repo: Path, tmp_path: Path, config: RepoConfig, *, creating: dict[str, str]
) -> list[str] | None:
    """What holds the unit's worktree once the profile's commands created `creating`, asked
    for through `build_worktree` as a unit's steps do; None when nothing does."""
    worktree = build_worktree({"app": repo}, root=tmp_path / "trees", repo=config)
    tree = worktree(unit(), "main")
    for name, text in creating.items():
        (tree / name).parent.mkdir(parents=True, exist_ok=True)
        (tree / name).write_text(text)
    try:
        worktree(unit(), "main")
    except DirtyWorktree as dirty:
        return sorted(dirty.paths)
    return None


def committed_files(tree: Path) -> list[str]:
    return git(tree, "show", "--name-only", "--format=", "HEAD").split()


def commit(tree: Path, config: RepoConfig) -> None:
    made = build_commit(unit_id=unit().id, repo=config, base="main")("feat: the work", cwd=tree)
    assert made == 1


# --- the worktree check -------------------------------------------------------------------


def test_a_file_the_profile_names_does_not_hold_a_repository_with_no_environment(
    repo: Path, tmp_path: Path
) -> None:
    config = without_environment(tmp_path, MAKES_LOCK.name)

    assert held_by(repo, tmp_path, config, creating={LOCK: "created\n"}) is None
    assert any((tmp_path / "trees").rglob(LOCK)), "and it is still there"


def test_another_uncommitted_file_holds_the_worktree_and_is_the_only_path_named(
    repo: Path, tmp_path: Path
) -> None:
    config = without_environment(tmp_path, MAKES_LOCK.name)

    held = held_by(repo, tmp_path, config, creating={LOCK: "created\n", "stray.txt": "mine\n"})

    assert held == ["stray.txt"]


def test_a_profile_that_names_nothing_leaves_the_file_a_leftover(
    repo: Path, tmp_path: Path
) -> None:
    config = without_environment(tmp_path, MAKES_NOTHING.name)

    assert held_by(repo, tmp_path, config, creating={LOCK: "created\n"}) == [LOCK]


def test_a_profile_without_the_hook_leaves_the_file_a_leftover(repo: Path, tmp_path: Path) -> None:
    config = without_environment(tmp_path, Hookless.name)

    assert held_by(repo, tmp_path, config, creating={LOCK: "created\n"}) == [LOCK]


@pytest.mark.parametrize(
    "profile, mine, theirs",
    [(MAKES_LOCK.name, LOCK, NESTED), (MAKES_NESTED.name, NESTED, LOCK)],
    ids=["flat", "nested"],
)
def test_each_profile_owns_only_the_files_it_names(
    repo: Path, tmp_path: Path, profile: str, mine: str, theirs: str
) -> None:
    config = without_environment(tmp_path, profile)

    assert held_by(repo, tmp_path / "a", config, creating={mine: "x\n"}) is None
    other = repository(tmp_path / "second")
    assert held_by(other, tmp_path / "b", config, creating={theirs: "x\n"}) == [theirs]


def test_an_unknown_profile_gets_the_environments_lists_and_no_error(
    repo: Path, tmp_path: Path
) -> None:
    env = FakeEnvironment(tmp_path / "control", inputs=(MANIFEST,), locks=(LOCK,))
    config = configured(tmp_path / "meta", "no-such-profile", env)

    assert held_by(repo, tmp_path, config, creating={LOCK: "created\n"}) is None
    assert owned_paths(config, repo) == {LOCK: Ownership.LOCK}


# --- the commit step ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "profile, name", [(MAKES_LOCK.name, LOCK), (MAKES_NESTED.name, NESTED)], ids=["flat", "nested"]
)
def test_the_untracked_file_is_not_committed_and_stays_in_the_worktree(
    repo: Path, tmp_path: Path, profile: str, name: str
) -> None:
    config = without_environment(tmp_path, profile)
    tree = worktree_of(repo, tmp_path, config)
    (tree / "marker.py").write_text("MARKER = 1\n")
    (tree / name).parent.mkdir(parents=True, exist_ok=True)
    (tree / name).write_text("created\n")

    commit(tree, config)

    assert committed_files(tree) == ["marker.py"], "the diff holds only the unit's own files"
    assert (tree / name).read_text() == "created\n"


def test_a_staged_file_the_profile_names_is_taken_out_of_the_commit(
    repo: Path, tmp_path: Path
) -> None:
    config = without_environment(tmp_path, MAKES_LOCK.name)
    tree = worktree_of(repo, tmp_path, config)
    (tree / "marker.py").write_text("MARKER = 1\n")
    (tree / LOCK).write_text("created\n")
    git(tree, "add", "-A")

    commit(tree, config)

    assert committed_files(tree) == ["marker.py"]
    assert (tree / LOCK).exists()


def test_a_profile_that_names_nothing_commits_every_file_as_before(
    repo: Path, tmp_path: Path
) -> None:
    config = without_environment(tmp_path, MAKES_NOTHING.name)
    tree = worktree_of(repo, tmp_path, config)
    (tree / "marker.py").write_text("MARKER = 1\n")
    (tree / LOCK).write_text("created\n")

    commit(tree, config)

    assert sorted(committed_files(tree)) == [LOCK, "marker.py"]


# --- a tracked file the profile names -----------------------------------------------------


def test_a_tracked_file_follows_the_lock_rule_when_a_dependency_input_changed(
    tracking: Path, tmp_path: Path
) -> None:
    config = with_environment(tmp_path, MAKES_LOCK.name)
    tree = worktree_of(tracking, tmp_path, config)
    (tree / MANIFEST).write_text('widget = "9"\n')
    (tree / LOCK).write_text("resolved for 9\n")

    commit(tree, config)

    assert sorted(committed_files(tree)) == [LOCK, MANIFEST]


def test_a_tracked_file_is_restored_when_no_dependency_input_changed(
    tracking: Path, tmp_path: Path
) -> None:
    config = with_environment(tmp_path, MAKES_LOCK.name)
    tree = worktree_of(tracking, tmp_path, config)
    (tree / "marker.py").write_text("MARKER = 1\n")
    (tree / LOCK).write_text("rewritten by a command\n")

    commit(tree, config)

    assert committed_files(tree) == ["marker.py"]
    assert (tree / LOCK).read_text() == "as committed\n"


def test_with_no_environment_a_tracked_file_the_profile_names_is_ordinary_work(
    tracking: Path, tmp_path: Path
) -> None:
    config = without_environment(tmp_path, MAKES_LOCK.name)
    worktree = build_worktree({"app": tracking}, root=tmp_path / "trees", repo=config)
    tree = worktree(unit(), "main")
    (tree / LOCK).write_text("edited by the unit\n")

    with pytest.raises(DirtyWorktree) as dirty:
        worktree(unit(), "main")
    commit(tree, config)

    assert dirty.value.paths == (LOCK,)
    assert git(tree, "show", f"HEAD:{LOCK}").strip() == "edited by the unit"


# --- a move of the branch -----------------------------------------------------------------


def test_a_restack_restores_a_tracked_file_the_profile_names_when_no_input_changed(
    tracking: Path, tmp_path: Path
) -> None:
    config = with_environment(tmp_path, MAKES_LOCK.name)
    tree = worktree_of(tracking, tmp_path, config)
    (tree / "marker.py").write_text("MARKER = 1\n")
    git(tree, "add", "-A")
    git(tree, "commit", "-qm", "the unit's work")
    (tracking / "trunk.py").write_text("TRUNK = 1\n")
    git(tracking, "add", "-A")
    git(tracking, "commit", "-qm", "trunk advances")
    (tree / LOCK).write_text("rewritten by a command\n")
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])

    moved = build_restack_onto(store, repo=config)(
        tree=tree, branch=BRANCH, base="main", unit=unit(), resolve=False
    )

    assert moved is not None and not moved.conflict
    assert git(tree, "rev-parse", "HEAD^") == git(tracking, "rev-parse", "main")
    assert (tree / LOCK).read_text() == "as committed\n"


# --- the owned set ------------------------------------------------------------------------


def test_the_profile_names_what_it_names(repo: Path, tmp_path: Path) -> None:
    assert owned_paths(without_environment(tmp_path, MAKES_LOCK.name), repo) == {
        LOCK: Ownership.CREATED
    }
    assert owned_paths(without_environment(tmp_path, MAKES_NESTED.name), repo) == {
        NESTED: Ownership.CREATED
    }


@pytest.mark.parametrize("profile", [MAKES_NOTHING.name, Hookless.name])
def test_a_profile_with_nothing_adds_none(repo: Path, tmp_path: Path, profile: str) -> None:
    assert owned_paths(without_environment(tmp_path, profile), repo) == {}
    assert owned_paths(None, repo) == {}


def test_a_path_the_profile_and_the_lock_inputs_both_name_is_one_lock_entry(
    repo: Path, tmp_path: Path
) -> None:
    env = FakeEnvironment(tmp_path / "control", inputs=(MANIFEST,), locks=(LOCK,))
    config = configured(tmp_path / "meta", MAKES_LOCK.name, env)

    assert owned_paths(config, repo) == {LOCK: Ownership.LOCK}


def test_a_path_the_profile_names_and_an_artifact_pattern_matches_is_an_artifact(
    repo: Path, tmp_path: Path
) -> None:
    env = FakeEnvironment(tmp_path / "control", inputs=(MANIFEST,), artifacts=("frontend",))
    config = configured(tmp_path / "meta", MAKES_NESTED.name, env)

    assert owned_paths(config, repo)[NESTED] is Ownership.ARTIFACT


def test_a_path_that_leaves_the_repository_or_names_the_git_directory_is_dropped(
    repo: Path, tmp_path: Path
) -> None:
    unusable = ["/etc/passwd", "../outside.lock", "sub/../../outside.lock", ".git", ".git/config"]
    profile = Creates("makes-unusable", *unusable, LOCK)

    with registered(profile):
        config = without_environment(tmp_path, profile.name)
        assert owned_paths(config, repo) == {LOCK: Ownership.CREATED}


def test_each_projects_paths_are_owned_under_its_path(repo: Path, tmp_path: Path) -> None:
    projects = [
        ProjectConfig(path="web", profile=MAKES_NESTED.name),
        ProjectConfig(path=".", profile=MAKES_NOTHING.name),
    ]
    config = configured(tmp_path / "meta", MAKES_LOCK.name, projects=projects)

    assert owned_paths(config, repo) == {
        LOCK: Ownership.CREATED,
        f"web/{NESTED}": Ownership.CREATED,
    }
