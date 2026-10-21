"""The per-group steps of a unit say which group is test-only."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import runtimes
from agent_build_kit.pipeline.stack_runner import UnitRunner
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import Member
from agent_build_kit.pipeline.wiring import build_runner
from tests.conftest import make_installation
from tests.factories import unit
from tests.runner_fakes import approving
from tests.runtimes.stand_in import StandInRuntime

TASKS = """# Tasks

Acceptance: none — a fixture about test-only groups

## 1. [app] [unit-test] Cover it

- [ ] 1.1 Test: it.
- [ ] 1.2 Do it.

## 2. [app] [e2e-test] Drive it

- [ ] 2.1 Test: it runs.
"""

OTHER_TASKS = TASKS.replace("[unit-test] Cover it", "[e2e-test] Carried drive")


def runner_with(root: Path, monkeypatch: pytest.MonkeyPatch, changes: dict[str, str]) -> UnitRunner:
    installation = make_installation(root)
    for change, text in changes.items():
        directory = root / "openspec" / "changes" / change
        directory.mkdir(parents=True)
        (directory / "tasks.md").write_text(text)
    monkeypatch.setattr(runtimes, "active", lambda: StandInRuntime(answer=approving()))
    return build_runner(
        unit("feature/1", change="feature"),
        store=UnitStore(root / "units.json"),
        installation=installation,
        log=lambda _: None,
    )


def test_the_steps_report_the_e2e_group_as_test_only_in_the_units_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = runner_with(tmp_path, monkeypatch, {"feature": TASKS})

    steps = runner.group_steps(unit("feature/1", change="feature", groups=(1, 2)))

    assert [(step.number, step.test_only) for step in steps] == [(1, False), (2, True)]


def test_a_carried_groups_tier_is_read_from_its_own_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = runner_with(tmp_path, monkeypatch, {"feature": TASKS, "other": OTHER_TASKS})
    carrier = unit(
        "feature/1",
        change="feature",
        groups=(1,),
        joined=(Member(change="other", groups=(1, 2)),),
    )

    steps = runner.group_steps(carrier)

    assert [(step.number, step.test_only) for step in steps] == [(1, False), (1, True), (2, True)]


def test_a_group_missing_from_tasks_is_not_test_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = runner_with(tmp_path, monkeypatch, {"feature": TASKS})

    steps = runner.group_steps(unit("feature/1", change="feature", groups=(2, 9)))

    assert [(step.number, step.test_only) for step in steps] == [(2, True), (9, False)]
