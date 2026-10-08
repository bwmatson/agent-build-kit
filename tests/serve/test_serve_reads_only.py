"""A read changes nothing, and an unknown field in `units.json` does not fail one
(spec: web-ui)."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

import httpx

from agent_build_kit.graph.checkpointer import open_checkpointer, unit_graphs_path
from agent_build_kit.graph.state import Node, UnitRun
from agent_build_kit.graph.unit import seed_thread
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.run_log import RunLog, run_log_dir
from agent_build_kit.pipeline.usage_report import GROUPINGS
from tests.factories import unit
from tests.ledger_lines import fixture_ledger
from tests.serving import EXPECTED, seed_pipeline, seed_review_round, snapshot


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


def test_an_unknown_field_in_the_unit_store_does_not_fail_a_read(
    inst: Installation, api: httpx.Client
) -> None:
    store = seed_pipeline(inst)
    document = json.loads(store.path.read_text())
    document["written_by"] = "a newer release"
    for item in document["units"]:
        item["a_field_from_a_newer_release"] = {"nested": [1, 2]}
    store.path.write_text(json.dumps(document, indent=2) + "\n")

    pipeline = api.get("/api/pipeline")
    one = api.get("/api/units/feature/2")

    assert pipeline.status_code == 200
    assert {item["id"] for item in pipeline.json()["units"]} == set(EXPECTED)
    assert one.status_code == 200
    assert one.json()["state"] == "in_review"


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


def test_an_unreadable_checkpoint_database_leaves_the_review_round_empty(
    inst: Installation, api: httpx.Client
) -> None:
    seed_pipeline(inst)
    unit_graphs_path(inst.state_dir).write_bytes(b"not a database, but long enough to be read " * 8)

    answer = api.get("/api/units/feature/2")

    assert answer.status_code == 200
    assert answer.json()["review_round"] is None
