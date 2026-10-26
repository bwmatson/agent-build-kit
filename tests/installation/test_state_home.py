"""Where an in-repo installation keeps its state: a planning home outside the repository, the same
from the working copy and the pipeline worktree, set by the environment, the ignored local file or
the tracked file, in that order (spec: planning-state-home)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.config import ConfigError
from agent_build_kit.installation import Installation, load_installation
from agent_build_kit.settings import settings
from tests.factories import init_repo
from tests.planning_worktree_support import in_repo, installation_at

SELF_REPO = "repos:\n  app:\n    path: .\n    slug: example/app\n"


@pytest.fixture(autouse=True)
def no_machine_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    """The ambient environment sets neither override; loading restores the settings after."""
    for key in ("planning_home", "state_dir"):
        monkeypatch.setattr(settings, key, None)
    monkeypatch.delenv("ABK_PLANNING_HOME", raising=False)
    monkeypatch.delenv("ABK_STATE_DIR", raising=False)


def loaded(root: Path, *, tracked: str = "", local: str | None = None) -> Installation:
    """The installation of a root whose abk.yaml lists its own repository, with `tracked` and
    `local` as the lines of its `planning:` block in abk.yaml and abk.local.yaml."""

    def block(lines: str) -> str:
        return f"planning:\n{lines}" if lines else ""

    (root / "abk.yaml").write_text(SELF_REPO + block(tracked))
    if local is not None:
        (root / "abk.local.yaml").write_text(block(local))
    return load_installation(config_path=root / "abk.yaml")


def test_the_state_is_in_the_planning_home_from_the_working_copy_and_the_worktree(
    tmp_path: Path, data: Path
) -> None:
    setup = in_repo(tmp_path)

    from_copy = installation_at(setup.working_copy, setup.working_copy)
    from_worktree = installation_at(setup.worktree, setup.working_copy)

    assert from_copy.state_dir == data / "app" / "planning" / "state"
    assert from_worktree.state_dir == from_copy.state_dir
    assert from_copy.planning_home == from_worktree.planning_home == data / "app" / "planning"
    assert from_copy.worktree_path == from_worktree.worktree_path
    assert from_copy.worktree_path == data / "app" / "planning" / "worktree"


def test_a_separate_planning_repo_and_a_root_with_no_git_keep_runs(
    tmp_path: Path, data: Path
) -> None:
    setup = in_repo(tmp_path)
    separate = init_repo(tmp_path / "meta")
    plain = tmp_path / "plain"

    for root in (separate, plain):
        inst = installation_at(root, setup.working_copy)
        assert not inst.in_repo
        assert inst.state_dir == inst.root / "runs"


def test_a_tracked_relative_state_dir_is_under_the_root(tmp_path: Path, data: Path) -> None:
    setup = in_repo(tmp_path)

    inst = installation_at(setup.working_copy, setup.working_copy, planning=dict(state_dir="runs"))

    assert inst.in_repo
    assert inst.state_dir == setup.working_copy / "runs"


def test_the_environment_beats_the_local_file_beats_the_tracked_file_for_the_state(
    tmp_path: Path, data: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup = in_repo(tmp_path)
    root = setup.working_copy
    tracked = f"  state_dir: {tmp_path / 'tracked'}\n"
    local = f"  state_dir: {tmp_path / 'local'}\n"

    assert loaded(root, tracked=tracked).state_dir == tmp_path / "tracked"
    assert loaded(root, tracked=tracked, local=local).state_dir == tmp_path / "local"
    monkeypatch.setenv("ABK_STATE_DIR", str(tmp_path / "env"))
    assert loaded(root, tracked=tracked, local=local).state_dir == tmp_path / "env"


def test_the_environment_beats_the_local_file_beats_the_tracked_file_for_the_home(
    tmp_path: Path, data: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup = in_repo(tmp_path)
    root = setup.working_copy
    tracked = f"  home: {tmp_path / 'tracked'}\n"
    local = f"  home: {tmp_path / 'local'}\n"

    only_tracked = loaded(root, tracked=tracked)
    assert only_tracked.planning_home == tmp_path / "tracked"
    both = loaded(root, tracked=tracked, local=local)
    assert both.planning_home == tmp_path / "local"
    assert both.state_dir == tmp_path / "local" / "state"
    assert both.worktree_path == tmp_path / "local" / "worktree"
    monkeypatch.setenv("ABK_PLANNING_HOME", str(tmp_path / "env"))
    every = loaded(root, tracked=tracked, local=local)
    assert every.planning_home == tmp_path / "env"
    assert every.state_dir == tmp_path / "env" / "state"
    assert every.worktree_path == tmp_path / "env" / "worktree"


def test_a_state_dir_with_a_tilde_moves_only_the_state(
    tmp_path: Path, data: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup = in_repo(tmp_path)
    home = tmp_path / "someone"
    monkeypatch.setenv("HOME", str(home))

    inst = installation_at(setup.working_copy, setup.working_copy, planning=dict(state_dir="~/s"))

    assert inst.state_dir == home / "s"
    assert inst.planning_home == data / "app" / "planning"
    assert inst.worktree_path == data / "app" / "planning" / "worktree"


def test_a_home_inside_the_repository_is_refused_naming_the_setting(
    tmp_path: Path, data: Path
) -> None:
    setup = in_repo(tmp_path)
    inside = setup.working_copy / "state-home"

    with pytest.raises(ConfigError, match=r"planning\.home") as refused:
        installation_at(setup.working_copy, setup.working_copy, planning=dict(home=str(inside)))

    assert str(inside) in str(refused.value)


def test_the_pages_default_beside_an_outside_state(tmp_path: Path, data: Path) -> None:
    setup = in_repo(tmp_path)

    inst = installation_at(setup.working_copy, setup.working_copy)

    assert inst.graph_page == inst.state_dir / "pages" / "unit_graph.md"
    assert inst.usage_page == inst.state_dir / "pages" / "unit_cost.md"


def test_a_separate_repo_keeps_its_pages_under_docs(tmp_path: Path, data: Path) -> None:
    setup = in_repo(tmp_path)
    separate = init_repo(tmp_path / "meta")

    inst = installation_at(separate, setup.working_copy)

    assert not inst.in_repo
    assert inst.graph_page == separate / "docs" / "unit_graph.md"
    assert inst.usage_page == separate / "docs" / "unit_cost.md"


def test_a_page_that_is_set_is_used_as_given(tmp_path: Path, data: Path) -> None:
    setup = in_repo(tmp_path)

    inst = installation_at(
        setup.working_copy,
        setup.working_copy,
        planning=dict(graph_page="docs/graph.md", usage_page="docs/cost.md"),
    )

    assert inst.state_dir == data / "app" / "planning" / "state"
    assert inst.graph_page == setup.working_copy / "docs" / "graph.md"
    assert inst.usage_page == setup.working_copy / "docs" / "cost.md"


def test_the_planning_paths_keep_the_outside_ones_absolute(tmp_path: Path, data: Path) -> None:
    setup = in_repo(tmp_path)

    inst = installation_at(setup.working_copy, setup.working_copy)

    assert str(inst.state_dir) in inst.planning_paths
    assert str(inst.graph_page) in inst.planning_paths
    assert str(inst.usage_page) in inst.planning_paths
    assert "openspec" in inst.planning_paths
