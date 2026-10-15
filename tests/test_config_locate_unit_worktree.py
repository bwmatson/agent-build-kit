"""`locate()` does not adopt a unit worktree's abk.yaml; the installation is the pipeline's."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.config import CONFIG_ENV, CONFIG_FILENAME, ConfigError, locate
from agent_build_kit.pipeline.planning_sync import remove_pipeline_marker
from tests.factories import commit_files, git
from tests.planning_worktree_support import InRepo, in_repo

UNIT_BRANCH = "spec/feature/1"


def _commit_config(setup: InRepo, prefix: str = "spec/") -> None:
    """Commit an abk.yaml to the working copy and move the pipeline worktree onto it."""
    commit_files(
        setup.working_copy, "config", {CONFIG_FILENAME: "git:\n  branch_prefix: " + prefix + "\n"}
    )
    git(setup.worktree, "checkout", "-q", "--detach", "main")


def _unit_worktree(setup: InRepo, branch: str = UNIT_BRANCH, name: str = "unit") -> Path:
    path = setup.working_copy.parent / name
    git(setup.working_copy, "worktree", "add", "-q", "-b", branch, str(path))
    return path


@pytest.fixture
def setup(tmp_path: Path) -> InRepo:
    made = in_repo(tmp_path)
    _commit_config(made)
    return made


def test_a_unit_worktree_resolves_to_the_pipeline_worktrees_file(setup: InRepo) -> None:
    unit = _unit_worktree(setup)
    assert (unit / CONFIG_FILENAME).is_file()

    assert locate(cwd=unit) == setup.worktree.resolve() / CONFIG_FILENAME


def test_a_directory_inside_a_unit_worktree_resolves_the_same(setup: InRepo) -> None:
    unit = _unit_worktree(setup)
    (unit / "src").mkdir()

    assert locate(cwd=unit / "src") == setup.worktree.resolve() / CONFIG_FILENAME


def test_with_no_marker_a_unit_worktree_raises_naming_the_worktree_and_the_two_ways(
    setup: InRepo,
) -> None:
    unit = _unit_worktree(setup)
    remove_pipeline_marker(setup.working_copy)

    with pytest.raises(ConfigError) as raised:
        locate(cwd=unit)

    message = str(raised.value)
    assert str(unit.resolve()) in message
    assert "--config" in message
    assert CONFIG_ENV in message


def test_a_marker_naming_a_missing_directory_raises_too(setup: InRepo) -> None:
    unit = _unit_worktree(setup)
    git(setup.working_copy, "worktree", "remove", "--force", str(setup.worktree))

    with pytest.raises(ConfigError, match="--config"):
        locate(cwd=unit)


def test_the_environment_names_the_file_for_an_agent_run(
    setup: InRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    unit = _unit_worktree(setup)
    named = setup.worktree.resolve() / CONFIG_FILENAME
    remove_pipeline_marker(setup.working_copy)
    monkeypatch.setenv(CONFIG_ENV, str(named))

    assert locate(cwd=unit) == named

    monkeypatch.delenv(CONFIG_ENV)
    with pytest.raises(ConfigError):
        locate(cwd=unit)


def test_an_explicit_path_wins_in_a_unit_worktree(setup: InRepo) -> None:
    unit = _unit_worktree(setup)
    explicit = setup.working_copy / CONFIG_FILENAME

    assert locate(explicit, cwd=unit) == explicit.resolve()
    assert locate(cwd=unit) == setup.worktree.resolve() / CONFIG_FILENAME


def test_a_linked_worktree_on_another_branch_keeps_its_own_file(setup: InRepo) -> None:
    other = _unit_worktree(setup, "feature/thing", "other")
    unit = _unit_worktree(setup)

    assert locate(cwd=other) == other.resolve() / CONFIG_FILENAME
    assert locate(cwd=unit) == setup.worktree.resolve() / CONFIG_FILENAME


def test_a_detached_linked_worktree_keeps_its_own_file(setup: InRepo) -> None:
    detached = setup.working_copy.parent / "detached"
    git(setup.working_copy, "worktree", "add", "-q", "--detach", str(detached), "main")
    unit = _unit_worktree(setup)

    assert locate(cwd=detached) == detached.resolve() / CONFIG_FILENAME
    assert locate(cwd=unit) == setup.worktree.resolve() / CONFIG_FILENAME


def test_the_main_working_tree_keeps_its_own_file_even_on_a_unit_shaped_branch(
    setup: InRepo,
) -> None:
    git(setup.working_copy, "checkout", "-q", "-b", UNIT_BRANCH)
    unit = _unit_worktree(setup, "spec/feature/2")

    assert locate(cwd=setup.working_copy) == setup.working_copy.resolve() / CONFIG_FILENAME
    assert locate(cwd=unit) == setup.worktree.resolve() / CONFIG_FILENAME


def test_the_pipeline_worktree_keeps_its_own_file(setup: InRepo) -> None:
    unit = _unit_worktree(setup)

    assert locate(cwd=setup.worktree) == setup.worktree.resolve() / CONFIG_FILENAME
    assert locate(cwd=unit) == setup.worktree.resolve() / CONFIG_FILENAME


def test_the_branch_pattern_follows_the_configured_prefix(tmp_path: Path) -> None:
    made = in_repo(tmp_path)
    _commit_config(made, prefix="agent/")
    default_prefixed = _unit_worktree(made, UNIT_BRANCH, "unit-default")
    own_prefixed = _unit_worktree(made, "agent/feature/1", "unit-agent")

    assert locate(cwd=default_prefixed) == default_prefixed.resolve() / CONFIG_FILENAME
    assert locate(cwd=own_prefixed) == made.worktree.resolve() / CONFIG_FILENAME


def test_a_branch_without_a_number_is_not_a_unit_branch(setup: InRepo) -> None:
    odd = _unit_worktree(setup, "spec/feature/one", "odd")
    unit = _unit_worktree(setup)

    assert locate(cwd=odd) == odd.resolve() / CONFIG_FILENAME
    assert locate(cwd=unit) == setup.worktree.resolve() / CONFIG_FILENAME
