"""A unit parked on the fix of a product defect shows in `abk status` as failed and waiting,
is requeued once when the fix's unit is in review and resumes, and `abk tick --dry-run`
previews the fix change of a recorded defect (spec: e2e-group-scope)."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.flakes import fix_change_name
from agent_build_kit.pipeline.product_defect import ProductDefectEntry, product_defect_record
from agent_build_kit.pipeline.unit_store import Cause, RequeueReason, UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, PLANNED
from agent_build_kit.pipeline.wiring import build_on_product_defect
from tests.cli.test_tick_dry_run_preview import inst, open_change, tree_bytes  # noqa: F401
from tests.conftest import run_status
from tests.factories import new_unit, stored_unit
from tests.pipeline.test_flake_fix_change import change_with_unit
from tests.product_defect_fakes import FIX, PREFIX, PRODUCT, REPRODUCTION, TEST, defect
from tests.wait_end_support import CHILD, Pipeline, pipeline

FIX_UNIT = f"{FIX}/1"


def parked(pipe: Pipeline) -> None:
    """`CHILD` met the defect, was given its `Needs:` line by the hook and was parked as the
    rework parks it: planned, gated with a resume requeue and no feedback, waiting on the fix
    change's unit, which is planned."""
    unit = change_with_unit(pipe.inst, "kid", CHILD)
    pipe.store.upsert([unit])
    fix = build_on_product_defect(pipe.store, pipe.inst, log=lambda line: None)(unit, defect())
    assert fix == FIX
    pipe.store.upsert([new_unit(FIX_UNIT), new_unit(CHILD, depends_on=(FIX_UNIT,))])
    pipe.store.set_state(CHILD, PLANNED, branch=f"spec/{CHILD}", cause=Cause.GATED)
    pipe.store.set_gated_requeue(CHILD, RequeueReason.RESUME)
    pipe.store.set_feedback(CHILD, "")


def test_the_parked_unit_shows_as_waiting_on_the_fix_unit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pipe = pipeline(tmp_path, monkeypatch)
    parked(pipe)

    lines = run_status(pipe.inst, monkeypatch, capsys)

    [line] = [line for line in lines if f"  {CHILD} (" in line and "waiting for" in line]
    assert FIX in line


def test_the_unit_is_released_once_when_the_fix_unit_is_in_review_and_resumes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pipe = pipeline(tmp_path, monkeypatch)
    parked(pipe)
    pipe.store.set_state(FIX_UNIT, IN_REVIEW, branch=f"spec/{FIX_UNIT}", pr=1)

    for _ in range(3):
        cli.release_gated(pipe.inst, pipe.store)

    [delivery] = pipe.host.deliveries
    assert (delivery["unit"], delivery["kind"]) == (CHILD, "requeue")
    assert delivery["reason"] == "resume"
    assert delivery["requeue"] is RequeueReason.RESUME, "it resumes, it is not reworked"
    assert pipe.store.get(CHILD).feedback == ""


def test_the_unit_is_not_released_while_the_fix_unit_is_planned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pipe = pipeline(tmp_path, monkeypatch)
    parked(pipe)

    for _ in range(3):
        cli.release_gated(pipe.inst, pipe.store)

    assert pipe.host.deliveries == []
    assert pipe.store.get(CHILD).state == PLANNED


# --- the dry run --------------------------------------------------------------------


def recorded(installation: Installation) -> None:
    UnitStore(installation.root / "units.json").upsert([stored_unit("feature/1", change="feature")])
    product_defect_record(installation).append(
        ProductDefectEntry(
            test=TEST,
            unit="feature/1",
            files=[PRODUCT],
            reproduction=REPRODUCTION,
            at=datetime(2026, 3, 1, 9, 30, tzinfo=UTC),
        )
    )


def dry_run(installation: Installation) -> int:
    return cli.cmd_tick(argparse.Namespace(dry_run=True), installation)


def test_a_dry_run_says_exists_for_a_recorded_defect_whose_change_is_open(
    inst: Installation,  # noqa: F811 — the fixture
    capsys: pytest.CaptureFixture[str],
) -> None:
    recorded(inst)
    name = fix_change_name(TEST, PREFIX)
    open_change(inst, name)
    before = tree_bytes(inst)
    capsys.readouterr()

    assert dry_run(inst) == 0

    lines = capsys.readouterr().out.splitlines()
    assert any(line.endswith(f"exists: {name}") for line in lines)
    assert tree_bytes(inst) == before


def test_a_dry_run_says_would_write_for_a_recorded_defect_and_writes_nothing(
    inst: Installation,  # noqa: F811 — the fixture
    capsys: pytest.CaptureFixture[str],
) -> None:
    recorded(inst)
    name = fix_change_name(TEST, PREFIX)
    before = tree_bytes(inst)
    record = product_defect_record(inst).path.read_bytes()
    capsys.readouterr()

    assert dry_run(inst) == 0

    lines = capsys.readouterr().out.splitlines()
    assert any(line.endswith(f"would write: {name}") for line in lines)
    assert not any(line.endswith(f"wrote: {name}") for line in lines)
    assert not (inst.changes_dir / name).exists()
    assert tree_bytes(inst) == before
    assert product_defect_record(inst).path.read_bytes() == record
