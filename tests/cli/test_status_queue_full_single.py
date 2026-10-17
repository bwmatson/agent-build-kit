"""A workspace whose only repo has one project reads as it always did: no project is named
(spec: unit-scheduling)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW
from tests.conftest import status_lines
from tests.factories import new_unit
from tests.project_workspace import repos_declaring


def test_a_single_project_workspace_at_its_limit_names_no_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repos = repos_declaring(tmp_path)
    del repos["platform"]

    def record(store: UnitStore) -> None:
        store.upsert([new_unit(f"r{n}/1") for n in range(5)])
        for n in range(5):
            store.set_state(f"r{n}/1", IN_REVIEW, pr=n + 1, branch=f"spec/r{n}/1")

    lines = status_lines(tmp_path, monkeypatch, capsys, record=record, repos=repos, limit=5)

    full = [line for line in lines if "queue is full" in line]
    assert len(full) == 1
    assert full[0].endswith(
        "queue is full: 5 units in progress, limit 5 (5 in review)"
        "; a priority-0 unit may still start while the emergency lane has room"
    )
