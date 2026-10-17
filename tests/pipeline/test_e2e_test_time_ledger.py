"""An e2e-test run writes one `test_time` row of the usage ledger for each entry it timed,
which the ledger's reader skips (spec: e2e-time-is-recorded-per-test).

The gate runs over a fake runner that answers with what pytest prints; the ledger is the
active installation's own.
"""

from pathlib import Path

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.usage_ledger import LEDGER_NAME, read_ledger
from tests.e2e_duration_fakes import (
    E2E,
    durations_output,
    recorded_times,
    run_e2e,
    time_line,
)

TEST = f"{E2E}::test_a"


def test_each_entry_is_a_row_with_its_unit_change_marker_test_phase_and_milliseconds(
    tmp_path: Path, workspace: Installation
) -> None:
    run_e2e(tmp_path, durations_output((842.0, "call", TEST), (571.5, "setup", TEST)))

    rows = recorded_times(workspace)

    assert [(r["test"], r["phase"], r["duration_ms"]) for r in rows] == [
        (TEST, "call", 842_000),
        (TEST, "setup", 571_500),
    ]
    for row in rows:
        assert (row["unit"], row["change"], row["marker"]) == (
            "add-marker/1",
            "add-marker",
            "local_stack",
        )
        assert row["at"]
        assert not {"agent_ms", "checks_ms", "other_ms"} & set(row)


def test_the_ledgers_reader_skips_the_rows(tmp_path: Path, workspace: Installation) -> None:
    run_e2e(tmp_path, durations_output((9.0, "call", TEST)))

    assert recorded_times(workspace)
    assert read_ledger(workspace.state_dir / LEDGER_NAME) == []


def test_a_split_line_adds_the_figures_to_the_row_of_its_test_and_phase(
    tmp_path: Path, workspace: Installation
) -> None:
    split = time_line(
        TEST,
        "call",
        agent={"implement": 100_000, "review": 20_000},
        calls={"implement": 2, "review": 1},
        checks_ms=30_000,
        other_ms=50_000,
    )
    output = durations_output((200.0, "call", TEST), (3.0, "setup", TEST), lines=(split,))
    run_e2e(tmp_path, output)

    rows = {row["phase"]: row for row in recorded_times(workspace)}

    figures = (rows["call"]["agent_ms"], rows["call"]["checks_ms"], rows["call"]["other_ms"])
    assert figures == (120_000, 30_000, 50_000)
    assert "agent_ms" not in rows["setup"]


@pytest.mark.parametrize("output", ["1 passed in 9.00s", ""])
def test_a_run_with_no_entries_writes_no_rows(
    tmp_path: Path, workspace: Installation, output: str
) -> None:
    run_e2e(tmp_path, durations_output((9.0, "call", TEST)))
    before = recorded_times(workspace)
    assert before

    run_e2e(tmp_path, output, "again")

    assert recorded_times(workspace) == before
