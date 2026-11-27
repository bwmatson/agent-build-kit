"""A read changes nothing, and an unknown field in `units.json` does not fail one
(spec: web-ui)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from agent_build_kit import orchestration
from agent_build_kit.graph.checkpointer import open_checkpointer, unit_graphs_path
from agent_build_kit.graph.state import Node, UnitRun
from agent_build_kit.graph.unit import Position, seed_thread
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.run_log import RunLog, run_log_dir
from agent_build_kit.pipeline.unit_graph_entry import register_unit_graph
from agent_build_kit.pipeline.usage_report import GROUPINGS
from agent_build_kit.serve.chat import Chat
from agent_build_kit.serve.server import review_round
from tests.conftest import make_installation
from tests.factories import stored_unit, unit
from tests.ledger_lines import fixture_ledger
from tests.serving import EXPECTED, hold_thread, seed_pipeline, seed_review_round, snapshot


def read_everything(api: httpx.Client, log_name: str) -> None:
    """Every read endpoint, each with a 200."""
    assert api.get("/api/pipeline").status_code == 200
    for uid in EXPECTED:
        assert api.get(f"/api/units/{uid}").status_code == 200
        assert api.get(f"/api/units/{uid}/logs").status_code == 200
    assert api.get(f"/api/units/feature/2/logs/{log_name}", params={"offset": 0}).status_code == 200
    for by in GROUPINGS:
        assert api.get("/api/usage", params={"by": by}).status_code == 200


def seed_run_log(inst: Installation) -> str:
    run = RunLog(
        run_log_dir(inst.state_dir),
        unit("feature/2", change="feature"),
        step="implement",
        model="model-x",
        base="main",
        started=datetime(2026, 9, 23, 23, 44, 5, tzinfo=UTC),
    )
    run.emit("[18:44:10] working")
    return run.name


def test_reading_leaves_the_store_ledger_logs_and_checkpoints_unchanged(
    inst: Installation, api: httpx.Client
) -> None:
    seed_pipeline(inst)
    seed_review_round(inst, "feature/2", 1)
    fixture_ledger(inst.state_dir / "usage-ledger.jsonl")
    name = seed_run_log(inst)
    before = snapshot(inst.state_dir)

    read_everything(api, name)
    read_everything(api, name)

    assert snapshot(inst.state_dir) == before


def test_reading_creates_no_checkpoint_database_where_there_is_none(
    inst: Installation, api: httpx.Client
) -> None:
    seed_pipeline(inst)
    name = seed_run_log(inst)
    before = snapshot(inst.state_dir)

    read_everything(api, name)

    assert snapshot(inst.state_dir) == before
    assert not list(inst.state_dir.glob("*.sqlite*"))


def test_reading_an_empty_installation_answers_and_creates_nothing(
    inst: Installation, api: httpx.Client
) -> None:
    before = snapshot(inst.state_dir)

    assert api.get("/api/pipeline").json()["units"] == []
    assert api.get("/api/usage", params={"by": "unit"}).json()["rows"] == []

    assert snapshot(inst.state_dir) == before


def test_an_empty_unknown_field_in_the_unit_store_does_not_fail_a_read(
    inst: Installation, api: httpx.Client
) -> None:
    store = seed_pipeline(inst)
    document = json.loads(store.path.read_text())
    document["written_by"] = "a newer release"
    for item in document["units"]:
        item["a_field_from_a_newer_release"] = {}
    store.path.write_text(json.dumps(document, indent=2) + "\n")

    pipeline = api.get("/api/pipeline")
    one = api.get("/api/units/feature/2")

    assert pipeline.status_code == 200
    assert {item["id"] for item in pipeline.json()["units"]} == set(EXPECTED)
    assert one.status_code == 200
    assert one.json()["state"] == "in_review"


def test_a_valued_unknown_field_in_the_unit_store_fails_a_read(
    inst: Installation, api: httpx.Client
) -> None:
    store = seed_pipeline(inst)
    document = json.loads(store.path.read_text())
    document["units"][0]["a_field_from_a_newer_release"] = "merged"
    store.path.write_text(json.dumps(document, indent=2) + "\n")

    assert api.get("/api/pipeline").status_code != 200


def test_a_read_while_a_writer_holds_the_checkpoints_open_changes_nothing(
    inst: Installation, api: httpx.Client
) -> None:
    seed_pipeline(inst)
    database = unit_graphs_path(inst.state_dir)
    wal = database.with_name(f"{database.name}-wal")

    async def scenario() -> httpx.Response:
        async with open_checkpointer(database) as saver:
            state = UnitRun(unit_id="feature/2", change="feature", review_round=2)
            await seed_thread(saver, state, as_node=Node.AWAIT_REVIEW)
            assert wal.exists() and wal.stat().st_size > 0
            before = snapshot(inst.state_dir)
            answer = await asyncio.to_thread(api.get, "/api/units/feature/2")
            assert snapshot(inst.state_dir) == before
            return answer

    answer = asyncio.run(scenario())

    assert answer.status_code == 200
    assert answer.json()["review_round"] == 2


@pytest.fixture
def store_inst(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Installation]:
    """An installation with a store configured, over a fresh registry of implementations."""
    orchestration.reset()
    installation = make_installation(
        tmp_path / "planning",
        planning={"worktree_root": str(tmp_path / "worktrees")},
        store={"url": "postgresql+asyncpg://user:secret@db.example:5432/units"},
    )
    monkeypatch.chdir(installation.root)
    yield installation
    orchestration.reset()


def test_with_a_store_the_review_round_comes_from_the_checkpoints_interface(
    store_inst: Installation, tmp_path: Path
) -> None:
    state = UnitRun(unit_id="feature/2", change="feature", review_round=3)
    hold_thread(state, tmp_path / "held.sqlite")

    assert review_round(store_inst, "feature/2") == 3
    assert not unit_graphs_path(store_inst.local_dir).exists()


class ClearingGraph:
    """A unit graph that records the units whose started node it is asked to clear."""

    def __init__(self) -> None:
        self.cleared: list[str] = []

    async def position(self, saver: Any, unit_id: str) -> Position:
        return Position()

    async def clear_running_node(self, saver: Any, unit_id: str) -> None:
        self.cleared.append(unit_id)


def test_with_a_store_forgetting_a_start_reaches_the_held_thread_without_a_sqlite_file(
    store_inst: Installation, tmp_path: Path
) -> None:
    hold_thread(UnitRun(unit_id="feature/2", change="feature"), tmp_path / "held.sqlite")
    graph = ClearingGraph()
    before = register_unit_graph(graph)
    chat = Chat(store_inst, units=lambda: [], recorded_session=lambda unit_id: None)

    try:
        chat.forget_start(stored_unit("feature/2", change="feature"))
    finally:
        register_unit_graph(before)

    assert graph.cleared == ["feature/2"]
    assert not unit_graphs_path(store_inst.local_dir).exists()


def test_an_unreadable_checkpoint_database_leaves_the_review_round_empty(
    inst: Installation, api: httpx.Client
) -> None:
    seed_pipeline(inst)
    unit_graphs_path(inst.state_dir).write_bytes(b"not a database, but long enough to be read " * 8)

    answer = api.get("/api/units/feature/2")

    assert answer.status_code == 200
    assert answer.json()["review_round"] is None
