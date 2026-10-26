"""Where the tracks keep their reports: the state directory when it is inside the planning root,
`docs/reports` when it is outside, a set value as given, and never outside the root (spec:
track-reports-dir)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.config import ConfigError
from agent_build_kit.settings import settings
from tests.planning_worktree_support import in_repo, installation_at


@pytest.fixture(autouse=True)
def no_machine_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("planning_home", "state_dir"):
        monkeypatch.setattr(settings, key, None)


def test_the_reports_are_in_the_state_directory_when_that_is_inside_the_root(
    tmp_path: Path, data: Path
) -> None:
    setup = in_repo(tmp_path)

    inst = installation_at(setup.working_copy, setup.working_copy, planning=dict(state_dir="runs"))

    assert inst.reports_dir == setup.working_copy / "runs"


def test_the_reports_are_under_docs_when_the_state_directory_is_outside_the_root(
    tmp_path: Path, data: Path
) -> None:
    setup = in_repo(tmp_path)

    for root in (setup.working_copy, setup.worktree):
        inst = installation_at(root, setup.working_copy)
        assert not inst.state_dir.is_relative_to(inst.root)
        assert inst.reports_dir == inst.root / "docs" / "reports"


def test_a_set_reports_directory_is_used_under_the_root(tmp_path: Path, data: Path) -> None:
    setup = in_repo(tmp_path)

    inst = installation_at(
        setup.working_copy, setup.working_copy, planning=dict(reports_dir="notes/tracks")
    )

    assert inst.reports_dir == setup.working_copy / "notes" / "tracks"


def test_a_reports_directory_outside_the_root_is_refused_naming_the_setting(
    tmp_path: Path, data: Path
) -> None:
    setup = in_repo(tmp_path)

    with pytest.raises(ConfigError, match=r"planning\.reports_dir"):
        inst = installation_at(
            setup.working_copy,
            setup.working_copy,
            planning=dict(reports_dir=str(tmp_path / "elsewhere")),
        )
        _ = inst.reports_dir
