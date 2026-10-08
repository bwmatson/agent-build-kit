"""The log endpoint: a run's lines from a byte offset, live until its outcome line,
with the host's clock stamps converted to UTC (spec: web-ui, run-logs).

A run's file is `unit`, `change`, `step`, `model`, `base` and `started` (UTC) header
lines, then `[HH:MM:SS] text` lines in the clock of the host that wrote them, then
`outcome: <result>` once it ends. The listing is `/api/units/<change>/<n>/logs` and a
run is read at `/api/units/<change>/<n>/logs/<name>?offset=<bytes>`, answering the
lines after the offset, the offset to ask from next, whether the run is `live` and,
once it has ended, its `outcome`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.run_log import RunLog, run_log_dir
from tests.factories import unit
from tests.serving import seed_pipeline

pytestmark = pytest.mark.usefixtures("new_york_clock")

# 18:44:05 on the host, which is UTC-5.
START = datetime(2026, 9, 23, 23, 44, 5, tzinfo=UTC)


def start_run(inst: Installation, started: datetime = START, step: str = "implement") -> RunLog:
    seed_pipeline(inst)
    return RunLog(
        run_log_dir(inst.state_dir),
        unit("feature/2", change="feature"),
        step=step,
        model="model-x",
        base="main",
        started=started,
    )


def read(api: httpx.Client, run: RunLog, offset: int = 0) -> dict:
    answer = api.get(f"/api/units/feature/2/logs/{run.name}", params={"offset": offset})
    assert answer.status_code == 200
    return answer.json()


def test_a_runs_lines_come_back_with_their_clock_in_utc(
    inst: Installation, api: httpx.Client
) -> None:
    run = start_run(inst)
    run.emit("[18:44:10] writing the tests")
    run.emit("[18:44:12] tests written")

    body = read(api, run)

    assert body["lines"] == [
        {"at": "2026-09-23T23:44:10+00:00", "text": "writing the tests"},
        {"at": "2026-09-23T23:44:12+00:00", "text": "tests written"},
    ]


def test_a_stamp_after_the_host_midnight_is_dated_by_the_start(
    inst: Installation, api: httpx.Client
) -> None:
    # Started 18:59:50 on the host; the next line is 19:00:02, past midnight in UTC.
    run = start_run(inst, started=datetime(2026, 9, 23, 23, 59, 50, tzinfo=UTC))
    run.emit("[18:59:58] before")
    run.emit("[19:00:02] after")

    body = read(api, run)

    assert [line["at"] for line in body["lines"]] == [
        "2026-09-23T23:59:58+00:00",
        "2026-09-24T00:00:02+00:00",
    ]


def test_a_line_in_the_second_the_run_starts_keeps_the_start_date(
    inst: Installation, api: httpx.Client
) -> None:
    run = start_run(inst, started=datetime(2026, 9, 23, 23, 44, 5, 734000, tzinfo=UTC))
    run.emit("[18:44:05] first")
    run.emit("[18:44:06] second")

    body = read(api, run)

    assert [line["at"] for line in body["lines"]] == [
        "2026-09-23T23:44:05+00:00",
        "2026-09-23T23:44:06+00:00",
    ]


def test_a_run_with_no_outcome_line_is_live_until_it_ends(
    inst: Installation, api: httpx.Client
) -> None:
    run = start_run(inst)
    run.emit("[18:44:10] working")

    assert read(api, run)["live"] is True

    run.close("ok")
    ended = read(api, run)

    assert ended["live"] is False
    assert ended["outcome"] == "ok"


def test_a_poll_from_the_offset_returns_only_what_was_appended(
    inst: Installation, api: httpx.Client
) -> None:
    run = start_run(inst)
    run.emit("[18:44:10] first")
    first = read(api, run)
    run.emit("[18:44:20] second")

    second = read(api, run, offset=first["offset"])

    assert [line["text"] for line in first["lines"]] == ["first"]
    assert second["lines"] == [{"at": "2026-09-23T23:44:20+00:00", "text": "second"}]
    assert second["offset"] > first["offset"]
    assert read(api, run, offset=second["offset"])["lines"] == []


def test_a_run_removed_between_polls_is_an_empty_answer_not_an_error(
    inst: Installation, api: httpx.Client
) -> None:
    run = start_run(inst)
    run.emit("[18:44:10] first")
    offset = read(api, run)["offset"]
    (run_log_dir(inst.state_dir) / run.name).unlink()

    body = read(api, run, offset=offset)

    assert body["lines"] == []
    assert body["missing"] is True
    assert body["live"] is False


def test_the_listing_names_a_units_runs_with_their_step_and_start(
    inst: Installation, api: httpx.Client
) -> None:
    run = start_run(inst, step="implement")

    body = api.get("/api/units/feature/2/logs").json()

    assert body["runs"] == [
        {
            "name": run.name,
            "step": "implement",
            "started": "2026-09-23T23:44:05+00:00",
            "live": True,
        }
    ]


def test_a_name_that_leaves_the_log_directory_is_not_found(
    inst: Installation, api: httpx.Client
) -> None:
    start_run(inst)
    (Path(inst.state_dir) / "secret.txt").write_text("not a log\n")

    answer = api.get("/api/units/feature/2/logs/..%2Fsecret.txt")

    assert answer.status_code == 404
