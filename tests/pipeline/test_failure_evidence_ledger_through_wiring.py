"""The ledger row `unit_test` writes is found from the `Flake` that `isolate` makes (spec:
test-failure-evidence): the row records the start of the whole run and the flake records the start
of the failing command, a later reading of the clock, and the evidence of a fix change joins them
by the run window."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import cast

import pytest

from agent_build_kit.pipeline.failure_evidence import change_evidence
from agent_build_kit.pipeline.flakes import FlakeFound
from agent_build_kit.pipeline.run_log import run_ledger_path
from agent_build_kit.pipeline.wiring import build_unit_test
from agent_build_kit.profiles.base import ToolchainProfile
from tests.failure_bundle_fakes import START, BundleMachine, BundleProfile


def test_the_row_a_run_writes_is_found_from_the_flake_its_isolation_makes(
    scratch: Path, tmp_path: Path
) -> None:
    ledger = run_ledger_path(tmp_path)
    clock = iter(START + timedelta(seconds=10 * n) for n in range(100))
    unit_test = build_unit_test(
        profile=cast(ToolchainProfile, BundleProfile()),
        run=BundleMachine(scratch, reruns=[0, 0]),
        changed=lambda *a: ["tests/test_one.py"],
        failures_dir=tmp_path / "bundles",
        test_runs=ledger,
        now=lambda: next(clock),
        machine=lambda: {"load": [2.5, 2.5, 2.5]},
    )

    with pytest.raises(FlakeFound) as found:
        unit_test(cwd=scratch, base="main")

    (flake,) = found.value.flakes[:1]
    assert flake.ran_at is not None
    assert flake.ran_at > START, "the failing command began after the run did"
    section = change_evidence(
        tmp_path,
        unit="add-marker/1",  # the unit the `scratch` fixture has running
        output=flake.output,
        bundle="",
        ran_at=flake.ran_at,
        conditions={},
    )
    assert "load_start" in section
    assert "workers" in section
