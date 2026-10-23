"""The runner `build_runner` assembles carries the real product-defect hook, so a report read in
a rework files its fix change and gives the unit its `Needs:` line (spec: e2e-group-scope)."""

from __future__ import annotations

from pathlib import Path

from tests.pipeline.test_e2e_gate_wiring import runner_of
from tests.pipeline.test_flake_fix_change import change_with_unit, changes, waits_on
from tests.product_defect_fakes import FIX, defect


def test_the_built_runner_files_the_fix_and_gives_the_unit_its_needs_line(
    tmp_path: Path,
) -> None:
    built, installation, store = runner_of(tmp_path)
    unit = change_with_unit(installation, "feature", "feature/1")
    store.upsert([unit])

    answer = built.on_product_defect(unit, defect())

    assert answer == FIX
    assert FIX in changes(installation)
    assert waits_on(installation, "feature") == [FIX]
