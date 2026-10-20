"""The runner `build_runner` assembles skips a scheduled split whose tests all need an unavailable
value, from the dimensions the installation's `abk.yaml` declares (spec: e2e-dimensions, "The
scheduler runs what is runnable")."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline import wiring
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.wiring import build_runner
from tests.conftest import make_installation
from tests.e2e_scope_fakes import branch
from tests.factories import stored_unit
from tests.pipeline.test_e2e_schedule_availability import FILES, Collecting


def test_a_scheduled_split_with_nothing_runnable_is_skipped_through_build_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installation = make_installation(
        tmp_path / "planning",
        repos={"app": {"path": str(tmp_path / "checkouts" / "app"), "slug": "example/app"}},
        limits={"e2e_unit_scope": "full"},
        tests={
            "e2e_splits": {
                "acp": {"marker": "runtime_acp"},
                "claude_code": {"marker": "runtime_claude_code"},
            },
            "e2e_dimensions": {
                "telemetry": {
                    "otel": {"marker": "telemetry_otel"},
                    "local": {"marker": "telemetry_local"},
                }
            },
            "e2e_available": {"telemetry": ["local"]},
        },
    )
    store = UnitStore(tmp_path / "units.json")
    unit = stored_unit("add-marker/1", repo="app", tier="e2e-test")
    store.upsert([unit])
    ran, log = Collecting(), []
    monkeypatch.setattr(wiring, "_run", ran)
    monkeypatch.setattr(wiring, "_head_sha", lambda cwd: "abc1234")
    built = build_runner(unit, store=store, installation=installation, log=log.append)
    repo, base = branch(tmp_path, None, base_files=FILES)

    ok, _ = built.run_e2e(cwd=repo, base=base, only="acp")

    assert ok
    assert any("nothing runnable: needs telemetry=otel" in line for line in log), log
    result = built.e2e_result()
    assert result is not None
    assert (result.failed, result.parked) == (0, [])
    assert ran.runs == []
    assert "skipped" in built.e2e_passed_note()
