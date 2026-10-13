"""Init's proposal is in the ledger: one `init_propose` row per attempt, the change written and the
repo proposed for, two rows when the proposal is repaired (spec: usage-accounting, every agent call
writes exactly one row)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.init.propose import propose
from agent_build_kit.installation import Installation
from agent_build_kit.runtimes import AgentRequest
from tests.call_rows import Spending, agent_rows
from tests.factories import init_repo
from tests.init.test_propose import BAD_TASKS, GOOD_TASKS, detection, valid_report, write_change

CHANGE = "app-testing-infrastructure"


@pytest.fixture
def planning(tmp_path: Path) -> Path:
    root = init_repo(tmp_path / "planning")
    (root / "openspec" / "changes").mkdir(parents=True)
    return root


def proposing(planning: Path, runtime: Spending) -> str:
    app = init_repo(planning.parent / "app")
    return propose(
        "app",
        detection(app),
        planning=planning,
        recommendations=planning / "none.md",
        kind="testing-infrastructure",
        run_openspec=valid_report(planning),
        repos=("platform", "app"),
        runtime=runtime,
    )


def test_a_valid_proposal_writes_one_init_propose_row(
    planning: Path, workspace: Installation
) -> None:
    def write(request: AgentRequest) -> None:
        assert request.cwd is not None
        write_change(request.cwd, CHANGE)

    proposing(planning, Spending(act=write))

    (row,) = agent_rows(workspace)
    assert (row["node"], row["unit"], row["change"], row["repo"], row["role"]) == (
        "init_propose",
        "",
        CHANGE,
        "app",
        "generic",
    )
    assert row["input_tokens"] == 1200


def test_a_repaired_proposal_writes_a_row_per_attempt(
    planning: Path, workspace: Installation
) -> None:
    tasks = iter([BAD_TASKS, GOOD_TASKS])

    def write(request: AgentRequest) -> None:
        assert request.cwd is not None
        write_change(request.cwd, CHANGE, next(tasks))

    proposing(planning, Spending(act=write))

    rows = agent_rows(workspace)
    assert [(row["node"], row["change"], row["repo"]) for row in rows] == [
        ("init_propose", CHANGE, "app")
    ] * 2
