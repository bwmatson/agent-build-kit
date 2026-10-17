"""The ready queue in `abk status` marks a unit that starts only in the emergency lane, and a
pass that starts nothing says what an ordinary start waits for.

Five places and four workers in each project; `app/web` is full and `app/api` is not."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.units import IN_REVIEW
from tests.cli.test_tick_scheduling import open_pr
from tests.conftest import ready_queue, run_status
from tests.emergency_lane_support import build, fresh, lane_workspace, seeded
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


def test_only_a_unit_that_starts_in_the_lane_alone_carries_the_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = lane_workspace(tmp_path, repos=repos_declaring(tmp_path, "app", ("web", "api")))
    seeded(
        inst,
        tmp_path,
        [
            *(build(f"w{n}/1", project="web") for n in range(4)),
            build("wrev/1", IN_REVIEW, project="web"),
            fresh("wzero/1", project="web", priority=0),
            fresh("wone/1", project="web", priority=1),
            fresh("azero/1", project="api", priority=0),
            fresh("aone/1", project="api", priority=1),
        ],
    )

    queue = ready_queue(run_status(inst, monkeypatch, capsys))

    # The marker follows the reason; a priority-1 unit and a priority-0 unit that fits the
    # normal limits carry none.
    assert {line.split(". ", 1)[1] for line in queue} == {
        "wzero/1 (app/web) — priority 0 (emergency room)",
        "wone/1 (app/web) — priority 1",
        "azero/1 (app/api) — priority 0",
        "aone/1 (app/api) — priority 1",
    }
    assert all("priority 0" in line for line in queue[:2])


def test_a_full_queue_says_an_ordinary_start_waits_except_a_priority_zero_unit_in_the_lane(
    builder: Builder, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = lane_workspace(tmp_path, repos=repos_declaring(tmp_path, "app"))
    for n in range(5):
        open_pr(builder, f"rev{n}/1", n + 1)
    builder.store.upsert([stored("ready/1", priority=1)])

    assert tick(inst) == 0

    out = capsys.readouterr().out
    assert builder.started == []
    assert (
        "no ordinary unit starts until the occupancy is below the limits, "
        "except a ready priority-0 unit while the lane has room"
    ) in out
