"""A track phase is in the ledger: one `track_<phase>` row per phase, the project as its repo, a
propose phase naming the change it writes, a failed phase written as `failed` (spec:
usage-accounting, every agent call writes exactly one row)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.tracks import runner
from tests.call_rows import Spending, agent_rows
from tests.tracks.test_runner import described_installation, project


@pytest.fixture
def inst(tmp_path: Path) -> Installation:
    return described_installation(tmp_path / "planning", tracks={"model": "haiku"})


def test_a_health_phase_writes_one_track_health_row_for_the_project(inst: Installation) -> None:
    runner.claude_phase(inst, project=project(inst), name="health", runtime=Spending())

    (row,) = agent_rows(inst)
    assert (row["node"], row["unit"], row["repo"], row["role"]) == (
        "track_health",
        "",
        "app",
        "generic",
    )
    assert row["model"] == "haiku"
    assert row["input_tokens"] == 1200


def test_a_propose_phase_carries_the_change_it_writes(inst: Installation) -> None:
    app = project(inst)

    runner.propose(inst, app, runtime=Spending())

    (row,) = agent_rows(inst)
    assert (row["node"], row["repo"]) == ("track_propose", "app")
    assert row["change"] == runner.proposed_change(app)


@pytest.mark.parametrize("name", ["improve", "recommend"])
def test_each_phase_is_named_for_itself(inst: Installation, name: str) -> None:
    runner.claude_phase(inst, project=project(inst), name=name, runtime=Spending())

    assert [row["node"] for row in agent_rows(inst)] == [f"track_{name}"]


def test_a_failed_phase_writes_its_row_as_failed(inst: Installation) -> None:
    runner.claude_phase(
        inst, project=project(inst), name="health", runtime=Spending(ok=False, error="boom")
    )

    (row,) = agent_rows(inst)
    assert (row["node"], row["outcome"]) == ("track_health", "failed")
    assert row["input_tokens"] == 1200
