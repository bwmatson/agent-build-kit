"""A tick calibrates the allowances once from the files on disk, however many units it decides.

Computed by the caller that holds the state directory, with no model call and no call to the
usage endpoint, and kept for the estimates that follow (spec: usage-pause)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline import usage_allowances
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.usage_allowances import ALLOWANCES_NAME
from tests.pipeline import test_cli_pipeline as base
from tests.pipeline.test_cli_pipeline import (  # noqa: F401 — fixtures
    FakeRunner,
    argv_namespace,
    healthy,
    isolated,
    stored,
)
from tests.usage_allowance_records import keep, per_unit

pytestmark = pytest.mark.usefixtures("scripted_engine")


def test_a_tick_with_two_units_calibrates_once_and_keeps_the_result(
    healthy,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    UnitStore(tmp_path / "units.json").upsert([stored(), stored("add-marker/2")])
    keep(tmp_path, *per_unit("weekly", [1] * 9))
    computed: list[int] = []
    real = usage_allowances.calibrated_allowances

    def counting(*args: object, **kwargs: object) -> object:
        computed.append(1)
        return real(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(usage_allowances, "calibrated_allowances", counting)
    built: list[str] = []
    monkeypatch.setattr(cli, "build_runner", lambda unit, **kwargs: FakeRunner(built))

    assert cli.cmd_tick(argv_namespace(dry_run=False), base.inst) == 0

    assert sorted(built) == ["add-marker/1", "add-marker/2"]
    assert computed == [1]
    kept = json.loads((tmp_path / ALLOWANCES_NAME).read_text())
    assert kept["weekly"]["pairs_used"] == 9
