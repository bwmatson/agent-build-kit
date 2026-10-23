"""The landing step reads the demotions live (spec: class-demotion, landing)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agent_build_kit.pipeline import demotion_record
from tests.landing_support import UNIT, landing

AT = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)


def test_an_auto_unit_approved_before_its_class_was_demoted_is_declined_until_a_lift(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    landed = landing(tmp_path, monkeypatch)
    path = landed.inst.state_dir / demotion_record.DEMOTIONS
    demotion_record.demote(
        path, unit_class="docs", trigger="revert", unit="c/9", at=AT, say=lambda message: None
    )

    landed.land()

    assert landed.forge.merged == []
    assert not landed.intent()
    assert any("demoted" in line for line in landed.logged), landed.logged

    demotion_record.lift(path, unit_class="docs", at=AT)
    landed.land()

    assert len(landed.forge.merged) == 1, landed.logged
    assert landed.store.get(UNIT).state == "merged"
