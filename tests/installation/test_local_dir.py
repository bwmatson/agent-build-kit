"""Where the machine-local files live: `planning.local_dir`, set by the environment, the ignored
local file or the tracked file, in that order, beside the state and not in it (spec:
planning-local-directory)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.config import ConfigError
from agent_build_kit.settings import settings
from tests.factories import init_repo
from tests.installation.test_state_home import loaded
from tests.planning_worktree_support import in_repo, installation_at


@pytest.fixture(autouse=True)
def no_machine_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    """The ambient environment sets none of the overrides; loading restores the settings after."""
    for key in ("planning_home", "state_dir", "local_dir"):
        monkeypatch.setattr(settings, key, None)
    for name in ("ABK_PLANNING_HOME", "ABK_STATE_DIR", "ABK_LOCAL_DIR"):
        monkeypatch.delenv(name, raising=False)


def test_an_in_repo_installation_keeps_the_local_files_beside_the_state(
    tmp_path: Path, data: Path
) -> None:
    setup = in_repo(tmp_path)

    inst = installation_at(setup.working_copy, setup.working_copy)

    assert inst.local_dir == data / "app" / "planning" / "local"
    assert inst.state_dir == data / "app" / "planning" / "state"


def test_the_planning_home_moves_the_local_directory(tmp_path: Path, data: Path) -> None:
    setup = in_repo(tmp_path)

    inst = loaded(setup.working_copy, tracked=f"  home: {tmp_path / 'home'}\n")

    assert inst.local_dir == tmp_path / "home" / "local"


def test_a_state_directory_set_elsewhere_leaves_the_local_directory(
    tmp_path: Path, data: Path
) -> None:
    setup = in_repo(tmp_path)

    inst = loaded(setup.working_copy, tracked=f"  state_dir: {tmp_path / 'share'}\n")

    assert inst.state_dir == tmp_path / "share"
    assert inst.local_dir == data / "app" / "planning" / "local"


def test_the_environment_beats_the_local_file_beats_the_tracked_file(
    tmp_path: Path, data: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = in_repo(tmp_path).working_copy
    tracked = f"  local_dir: {tmp_path / 'tracked'}\n"
    local = f"  local_dir: {tmp_path / 'local'}\n"

    assert loaded(root, tracked=tracked).local_dir == tmp_path / "tracked"
    assert loaded(root, tracked=tracked, local=local).local_dir == tmp_path / "local"
    monkeypatch.setenv("ABK_LOCAL_DIR", str(tmp_path / "env"))
    assert loaded(root, tracked=tracked, local=local).local_dir == tmp_path / "env"


def test_a_relative_local_directory_is_refused_naming_the_setting(
    tmp_path: Path, data: Path
) -> None:
    root = in_repo(tmp_path).working_copy

    with pytest.raises(ConfigError, match=r"planning\.local_dir"):
        loaded(root, tracked="  local_dir: tmp/local\n")


def test_a_separate_planning_repo_keeps_the_local_files_in_the_state_directory(
    tmp_path: Path, data: Path
) -> None:
    setup = in_repo(tmp_path)
    separate = init_repo(tmp_path / "meta")

    inst = installation_at(separate, setup.working_copy)

    assert inst.state_dir == inst.root / "runs"
    assert inst.local_dir == inst.state_dir
