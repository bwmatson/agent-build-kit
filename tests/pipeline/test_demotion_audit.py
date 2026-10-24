"""An audit recorded `wrong` demotes the unit's class with the trigger `audit`; `ok` demotes
nothing (spec: class-demotion, a failed audit demotes the class)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_build_kit.cli import main
from agent_build_kit.config import dump
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import audit_record, demotion_record
from tests.conftest import make_installation

AT = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)


@pytest.fixture
def inst(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Installation:
    installation = make_installation(
        tmp_path / "planning",
        review=dict(
            enabled=True,
            classes={"docs": ["docs/**"], "code": ["src/**"]},
            auto_land=dict(classes=["docs", "code"]),
        ),
    )
    (installation.root / "abk.yaml").write_text(dump(installation.config))
    monkeypatch.chdir(installation.root)
    audits = installation.state_dir / audit_record.AUDITS
    audit_record.record_awaiting(audits, unit="feature/1", unit_class="docs", at=AT)
    audit_record.record_awaiting(audits, unit="feature/2", unit_class="code", at=AT)
    return installation


def audit(unit: str, result: str) -> None:
    assert main(["review", "audit", unit, result]) == 0


def demoted(inst: Installation) -> dict[str, dict]:
    return demotion_record.read_demotions(inst.state_dir / demotion_record.DEMOTIONS)


def test_an_audit_recorded_wrong_demotes_the_class_with_the_trigger_and_the_unit(
    inst: Installation,
) -> None:
    audit("feature/1", "wrong")

    assert list(demoted(inst)) == ["docs"]
    assert [(t["trigger"], t["unit"]) for t in demoted(inst)["docs"]["triggers"]] == [
        ("audit", "feature/1")
    ]


def test_an_audit_recorded_ok_demotes_nothing(inst: Installation) -> None:
    audit("feature/1", "ok")
    audit("feature/2", "wrong")

    assert list(demoted(inst)) == ["code"]
