"""Rounds over a store seeded without a planning repo: the unstarted units' changes exist.

The planning step drops an unstarted unit whose change has no directory, so a test that
seeds units straight into the store and runs the real planning step gives each such unit's
change a directory first.
"""

from __future__ import annotations

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.units import PLANNED


def keep_changes_of_unstarted_units(monkeypatch: pytest.MonkeyPatch) -> None:
    planning = cli.plan_all

    def plan_all(inst, *, store, **kwargs):
        for unit in store.all():
            if unit.state == PLANNED and unit.unstarted:
                (inst.changes_dir / unit.change).mkdir(parents=True, exist_ok=True)
        return planning(inst, store=store, **kwargs)

    monkeypatch.setattr(cli, "plan_all", plan_all)
