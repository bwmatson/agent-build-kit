"""The web server shows a superseded unit as closed with its pieces, and a piece of a split has
run logs of its own (spec: unit-superseding)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.run_log import RunLog, run_log_dir
from tests.factories import superseded_store, unit

START = datetime(2026, 9, 23, 23, 44, 5, tzinfo=UTC)


def run_of(inst: Installation, uid: str, started: datetime) -> RunLog:
    return RunLog(
        run_log_dir(inst.state_dir),
        unit(uid, change="app"),
        step="implement",
        model="model-x",
        base="main",
        started=started,
    )


def test_the_summary_of_a_superseded_unit_is_closed_with_its_pieces(
    inst: Installation, api: httpx.Client
) -> None:
    superseded_store(inst.state_dir)

    listed = {item["id"]: item for item in api.get("/api/pipeline").json()["units"]}

    assert listed["app/3"]["state"] == "closed"
    assert listed["app/3"]["replaced_by"] == ["app/3-s1", "app/3-s2"]


def test_each_unit_lists_only_its_own_run_logs(inst: Installation, api: httpx.Client) -> None:
    superseded_store(inst.state_dir)
    parent = run_of(inst, "app/3", START)
    piece = run_of(inst, "app/3-s1", START + timedelta(minutes=5))

    def names(path: str) -> list[str]:
        return [run["name"] for run in api.get(path).json()["runs"]]

    assert names("/api/units/app/3/logs") == [parent.name]
    assert names("/api/units/app/3-s1/logs") == [piece.name]
    assert api.get(f"/api/units/app/3-s1/logs/{piece.name}").status_code == 200
    assert api.get(f"/api/units/app/3/logs/{piece.name}").status_code == 404
