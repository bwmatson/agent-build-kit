"""A build that ends on a pull request the forge shows merged or closed has it recorded by the
tick, once the build has released the unit's branch lock."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.units import CLOSED, RUNNING, SETTLING
from tests.tick_driver import UNIT, make_setup


@pytest.mark.parametrize(("shown", "recorded"), [("merged", SETTLING), ("closed", CLOSED)])
def test_the_tick_records_what_the_forge_showed_after_the_build_released_its_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, shown: str, recorded
) -> None:
    graph = make_setup(tmp_path, monkeypatch)
    graph.store.set_state(UNIT, RUNNING, pr=7, branch=f"spec/{UNIT}")
    graph.options["forge_state"] = lambda unit, pr: shown

    assert graph.tick() == 0

    assert graph.store.get(UNIT).state == recorded
    assert not any("in review" in line for line in graph.recorder.logged), graph.recorder.logged
