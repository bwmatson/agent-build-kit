"""The runner names a change's directory, and reads its follow-ups, under the
configured `planning.specs_dir` rather than a fixed `openspec`."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import runtimes
from agent_build_kit.pipeline.stack_runner import UnitRunner
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.wiring import build_runner
from tests.conftest import make_installation
from tests.factories import unit
from tests.runner_fakes import approving
from tests.runtimes.stand_in import StandInRuntime

FOLLOW_UPS = "## From `feature/1`\n\n- Name the lock after what it guards\n"


def runner_in(root: Path, monkeypatch: pytest.MonkeyPatch, **planning: str) -> UnitRunner:
    installation = make_installation(root, planning=planning)
    monkeypatch.setattr(runtimes, "active", lambda: StandInRuntime(answer=approving()))
    return build_runner(
        unit("feature/1", change="feature"),
        store=UnitStore(root / "units.json"),
        installation=installation,
        log=lambda _: None,
    )


def test_a_configured_specs_directory_is_where_the_change_is_named_and_the_default_is_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured = runner_in(tmp_path / "configured", monkeypatch, specs_dir="specs")
    default = runner_in(tmp_path / "default", monkeypatch)

    assert configured.change_dir("feature") == f"{tmp_path / 'configured'}/specs/changes/feature"
    assert default.change_dir("feature") == f"{tmp_path / 'default'}/openspec/changes/feature"


def test_follow_ups_are_read_from_the_configured_specs_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = runner_in(tmp_path, monkeypatch, specs_dir="specs")
    change = tmp_path / "specs" / "changes" / "feature"
    change.mkdir(parents=True)
    (change / "follow-ups.md").write_text(FOLLOW_UPS)

    assert runner.follow_ups_for(unit("feature/1", change="feature")) == [
        "Name the lock after what it guards"
    ]
