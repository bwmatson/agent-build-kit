"""The scratch change the e2e-test build test plans must pass the authoring contract.

E2e-test runs on the host and fails quietly when nothing is planned, so the
contract is checked here, where CI sees it.
"""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline import work_graph
from tests.integration.test_build_unit import TASKS


def test_the_e2e_scratch_change_passes_the_authoring_contract(tmp_path: Path) -> None:
    tasks = tmp_path / "tasks.md"
    tasks.write_text(TASKS)

    _, errors = work_graph.validate_tasks(tasks, repos=("app",))

    assert errors == []
