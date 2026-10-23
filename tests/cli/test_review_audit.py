"""`abk review audit <unit> ok|wrong` records the result of an audit and changes nothing else
(spec: auto-land, a sampled share of landed units is audited)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_build_kit.cli import main
from agent_build_kit.config import dump
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import audit_record
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.verdict_record import VERDICTS
from tests.conftest import make_installation
from tests.factories import new_unit
from tests.review_records import sample_records, write_records

PICKED = "feature/1"
OTHER = "feature/2"
AT = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)


@pytest.fixture
def inst(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Installation:
    installation = make_installation(
        tmp_path / "planning",
        review=dict(enabled=True, classes={"docs": ["docs/**"]}, auto_land=dict(classes=["docs"])),
    )
    (installation.root / "abk.yaml").write_text(dump(installation.config))
    monkeypatch.chdir(installation.root)
    UnitStore(installation.state_dir / "units.json").upsert(
        [new_unit(PICKED), new_unit(OTHER), new_unit("feature/3")]
    )
    audits = installation.state_dir / audit_record.AUDITS
    audit_record.record_awaiting(audits, unit=PICKED, unit_class="docs", at=AT)
    audit_record.record_awaiting(audits, unit=OTHER, unit_class="docs", at=AT)
    return installation


def audit(capsys: pytest.CaptureFixture[str], *words: str) -> tuple[int, str]:
    """The exit code of `abk review audit <words>` and everything it printed."""
    capsys.readouterr()
    try:
        code = main(["review", "audit", *words])
    except SystemExit as stop:
        code = stop.code if isinstance(stop.code, int) else 1
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def recorded(inst: Installation) -> dict[str, dict]:
    return audit_record.read_audits(inst.state_dir / audit_record.AUDITS)


@pytest.mark.parametrize("result", ["ok", "wrong"])
def test_a_result_is_recorded_and_reported(
    inst: Installation, capsys: pytest.CaptureFixture[str], result: str
) -> None:
    code, output = audit(capsys, PICKED, result)

    assert code == 0, output
    assert PICKED in output and result in output
    assert recorded(inst)[PICKED]["state"] == result
    assert recorded(inst)[OTHER]["state"] == audit_record.AWAITING


def test_an_unknown_unit_is_refused_with_a_message(
    inst: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    before = (inst.state_dir / audit_record.AUDITS).read_bytes()

    code, output = audit(capsys, "feature/99", "ok")

    assert code != 0
    assert "feature/99" in output
    assert (inst.state_dir / audit_record.AUDITS).read_bytes() == before


def test_a_unit_not_awaiting_audit_is_refused_with_a_message(
    inst: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    before = (inst.state_dir / audit_record.AUDITS).read_bytes()

    code, output = audit(capsys, "feature/3", "ok")

    assert code != 0
    assert "not awaiting audit" in output
    assert (inst.state_dir / audit_record.AUDITS).read_bytes() == before


def test_a_unit_already_audited_is_refused(
    inst: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    assert audit(capsys, PICKED, "ok")[0] == 0

    code, output = audit(capsys, PICKED, "wrong")

    assert code != 0
    assert "not awaiting audit" in output
    assert recorded(inst)[PICKED]["state"] == "ok"


def test_a_word_other_than_ok_or_wrong_is_refused(
    inst: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _ = audit(capsys, PICKED, "fine")

    assert code != 0
    assert recorded(inst)[PICKED]["state"] == audit_record.AWAITING


def test_the_command_changes_nothing_but_the_audit_record(
    inst: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    write_records(inst.state_dir / VERDICTS, sample_records())
    files = [inst.root / "abk.yaml", inst.state_dir / VERDICTS, inst.state_dir / "units.json"]
    before = [f.read_bytes() for f in files]
    others = recorded(inst)[OTHER]

    assert audit(capsys, PICKED, "wrong")[0] == 0

    assert [f.read_bytes() for f in files] == before
    assert recorded(inst)[OTHER] == others
