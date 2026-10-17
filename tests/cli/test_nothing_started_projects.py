"""A pass that starts nothing names the full projects that hold ready units back, and no other
(spec: unit-scheduling)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import HELD, IN_REVIEW, PLANNED
from tests.cli.test_tick_scheduling import open_pr
from tests.conftest import make_installation
from tests.project_workspace import repos_declaring
from tests.tick_pass import Builder, install_builder, isolate, stored, tick, warm_unit_graphs

pytestmark = pytest.mark.usefixtures("scripted_engine")


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    warm_unit_graphs(tmp_path)
    isolate(monkeypatch)


@pytest.fixture
def builder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Builder:
    return install_builder(tmp_path, monkeypatch)


def test_the_reason_names_the_full_project_that_holds_a_ready_unit_back_and_no_other(
    builder: Builder, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = make_installation(
        tmp_path,
        repos=repos_declaring(tmp_path, "app", ("web", "api")),
        planning=dict(state_dir=".", worktree_root=str(tmp_path.parent / "trees")),
        project_limits=dict(max_units_in_progress=2),
    )
    for n in (1, 2):
        open_pr(builder, f"web{n}/1", n, project="web")
        open_pr(builder, f"api{n}/1", 10 + n, project="api")
    builder.store.upsert(
        [
            stored("ready/1", project="web"),
            stored("webheld/1", project="web"),
            stored("apiheld/1", project="api"),
            stored("webblocked/1", project="web", depends_on=("webheld/1",)),
            stored("apiblocked/1", project="api", depends_on=("apiheld/1",)),
        ]
    )
    for uid in ("webheld/1", "apiheld/1"):
        builder.store.set_state(uid, HELD, note="held", cause=Cause.GATED)
    for uid in ("webblocked/1", "apiblocked/1"):
        builder.store.set_state(uid, PLANNED, branch=f"spec/{uid}")

    assert tick(inst) == 0

    out = capsys.readouterr().out
    assert builder.started == []
    assert builder.store.get("ready/1").state == PLANNED
    assert builder.store.get("web1/1").state == IN_REVIEW
    assert "queue is full: app/web: 2 units in progress, limit 2 (2 in review)" in out
    assert "no new unit starts until one finishes or is closed" in out
    assert "blocked: webblocked/1 (app/web) waits on webheld/1" in out
    assert "app/api" not in out


def test_a_pass_with_nothing_ready_names_a_candidate_by_its_project(
    builder: Builder, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = make_installation(
        tmp_path,
        repos=repos_declaring(tmp_path, "app", ("web",)),
        planning=dict(state_dir=".", worktree_root=str(tmp_path.parent / "trees")),
    )
    builder.store.upsert(
        [stored("held/1", project="web"), stored("waiter/1", project="web", depends_on=("held/1",))]
    )
    builder.store.set_state("held/1", HELD, note="held", cause=Cause.GATED)

    assert tick(inst) == 0

    assert "waiter/1 (app/web):" in capsys.readouterr().out
