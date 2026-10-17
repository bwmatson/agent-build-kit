"""The status prints a queue line for each project at its limit, and each counts only its own
units (spec: unit-scheduling)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import FAILED, IN_REVIEW, PLANNED, RUNNING
from tests.conftest import status_lines
from tests.factories import new_unit
from tests.project_workspace import repos_declaring

LIMIT = 9


def two_full_projects(store: UnitStore) -> None:
    """`app/web`: seven failed and two running, with a blocked unit; `app/api`: nine in review,
    with a failed unit that waits on a unit not yet started."""
    store.upsert(
        [
            *[new_unit(f"w{n}/1", project="web") for n in range(9)],
            *[new_unit(f"a{n}/1", project="api") for n in range(9)],
            new_unit("wblocked/1", project="web", depends_on=("w8/1",)),
            new_unit("pending/1", project="api"),
            new_unit("awaiting/1", project="api", depends_on=("pending/1",)),
        ]
    )
    for n in range(7):
        store.set_state(f"w{n}/1", FAILED, note="broke", branch=f"spec/w{n}/1")
    for n in (7, 8):
        store.set_state(f"w{n}/1", RUNNING, branch=f"spec/w{n}/1")
    for n in range(9):
        store.set_state(f"a{n}/1", IN_REVIEW, pr=n + 1, branch=f"spec/a{n}/1")
    store.set_state("wblocked/1", PLANNED, branch="spec/wblocked/1")
    store.set_state("awaiting/1", FAILED, note="broke", branch="spec/awaiting/1")


def full_lines(lines: list[str]) -> list[str]:
    return [line for line in lines if "queue is full" in line]


def test_each_project_at_its_limit_gets_its_own_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = status_lines(
        tmp_path,
        monkeypatch,
        capsys,
        record=two_full_projects,
        repos=repos_declaring(tmp_path, "app", ("web", "api")),
        limit=LIMIT,
    )

    full = full_lines(lines)
    assert len(full) == 2
    web = next(line for line in full if "app/web" in line)
    api = next(line for line in full if "app/api" in line)
    assert "queue is full: app/web: 9 units in progress, limit 9 (7 failed, 2 running)" in web
    assert "queue is full: app/api: 9 units in progress, limit 9 (9 in review)" in api


def test_a_project_below_its_limit_has_no_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def record(store: UnitStore) -> None:
        two_full_projects(store)
        store.upsert([new_unit("root/1")])
        store.set_state("root/1", IN_REVIEW, pr=99, branch="spec/root/1")

    lines = status_lines(
        tmp_path,
        monkeypatch,
        capsys,
        record=record,
        repos=repos_declaring(tmp_path, "app", ("web", "api")),
        limit=LIMIT,
    )

    full = full_lines(lines)
    assert len(full) == 2
    assert all("app/web" in line or "app/api" in line for line in full)


def test_each_line_counts_only_its_own_projects_blocked_and_failed_waiting_units(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = status_lines(
        tmp_path,
        monkeypatch,
        capsys,
        record=two_full_projects,
        repos=repos_declaring(tmp_path, "app", ("web", "api")),
        limit=LIMIT,
    )

    full = full_lines(lines)
    web = next(line for line in full if "app/web" in line)
    api = next(line for line in full if "app/api" in line)
    assert web.endswith("(7 failed, 2 running); 1 blocked not counted")
    assert api.endswith("(9 in review); 1 failed waiting not counted")
