"""Reading a run log whose replies run over several lines, and one written
before they did (spec: run-logs)."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.run_log import RunLog, run_log_dir
from tests.factories import unit
from tests.serving import seed_pipeline

pytestmark = pytest.mark.usefixtures("new_york_clock")

START = datetime(2026, 9, 23, 23, 44, 5, tzinfo=UTC)  # 18:44:05 on the host


def start_run(inst: Installation) -> RunLog:
    seed_pipeline(inst)
    return RunLog(
        run_log_dir(inst.state_dir),
        unit("feature/2", change="feature"),
        step="implement",
        model="model-x",
        base="main",
        started=START,
    )


def read(api: httpx.Client, run: RunLog, offset: int = 0) -> dict:
    answer = api.get(f"/api/units/feature/2/logs/{run.name}", params={"offset": offset})
    assert answer.status_code == 200
    return answer.json()


def texts(body: dict) -> list[str]:
    return [line["text"] for line in body["lines"]]


def test_every_continuation_line_belongs_to_the_reply_that_began_it(
    inst: Installation, api: httpx.Client
) -> None:
    run = start_run(inst)
    run.emit("[18:44:10]   says: first paragraph\n\nsecond paragraph\n  nested")
    run.emit("[18:44:12] review: approved")

    body = read(api, run)

    assert [line["at"] for line in body["lines"]] == [
        "2026-09-23T23:44:10+00:00",
        "2026-09-23T23:44:12+00:00",
    ]
    assert texts(body) == [
        "  says: first paragraph\n\nsecond paragraph\n  nested",
        "review: approved",
    ]


def test_a_reply_is_one_entry_however_the_poll_splits_the_file(
    inst: Installation, api: httpx.Client
) -> None:
    run = start_run(inst)
    run.emit("[18:44:10] says: first\nsecond\nthird")
    first_poll = read(api, run)
    run.emit("[18:44:12] next")

    second_poll = read(api, run, offset=first_poll["offset"])

    assert texts(first_poll) == ["says: first\nsecond\nthird"]
    assert texts(second_poll) == ["next"]


def test_an_older_log_with_clipped_replies_reads_as_written(
    inst: Installation, api: httpx.Client
) -> None:
    run = start_run(inst)
    run.emit("[18:44:10]   says: First I will read the spec and the tests that pin it. Then I…")
    run.emit("[18:44:11] implement: committed")
    run.emit("[18:44:12]   says: and a newer\nwhole reply")
    run.close("done")

    body = read(api, run)

    assert texts(body) == [
        "  says: First I will read the spec and the tests that pin it. Then I…",
        "implement: committed",
        "  says: and a newer\nwhole reply",
    ]
    assert body["outcome"] == "done"
