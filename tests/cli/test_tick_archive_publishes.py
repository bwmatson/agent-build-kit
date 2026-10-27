"""The tick's archive step and `abk verify` both hand the archive a publish hook and the tracking
copy's folder, so a change archived by either is committed the same way."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.archive import archive_ready_changes
from agent_build_kit.pipeline.task_progress import progress_dir
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.verify import Verification
from tests.factories import commit_files, git, init_repo, stored_unit
from tests.tick_driver import Setup, make_setup

pytestmark = pytest.mark.usefixtures("scripted_engine")


def recording(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """`archive_ready_changes` as the real one, recording the keywords it was called with."""
    calls: list[dict[str, Any]] = []

    def archive(units, **kwargs):
        calls.append(kwargs)
        return archive_ready_changes(units, **kwargs)

    monkeypatch.setattr(cli, "archive_ready_changes", archive)
    return calls


def test_a_tick_passes_the_publish_hook_and_the_copy_folder_and_commits_nothing_when_idle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup: Setup = make_setup(tmp_path, monkeypatch)
    calls = recording(monkeypatch)
    commit_files(init_repo(tmp_path), "start", {"README.md": "planning\n"})
    before = git(tmp_path, "rev-list", "--count", "HEAD")

    setup.tick()

    assert len(calls) == 1
    assert callable(calls[0]["publish"])
    assert calls[0]["progress"]("feature") == progress_dir(setup.inst, "feature")
    assert git(tmp_path, "rev-list", "--count", "HEAD") == before


def test_verify_passes_the_same_hook_and_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup: Setup = make_setup(tmp_path, monkeypatch)
    calls = recording(monkeypatch)
    UnitStore(setup.inst.state_dir / "units.json").upsert(
        [stored_unit("feature/1", state="merged")]
    )
    monkeypatch.setattr(
        cli, "verify_one", lambda inst, change, units: Verification(change=change, passed=True)
    )

    cli.cmd_verify(argparse.Namespace(change="feature"), setup.inst)

    assert len(calls) == 1
    assert callable(calls[0]["publish"])
    assert calls[0]["progress"]("feature") == progress_dir(setup.inst, "feature")
