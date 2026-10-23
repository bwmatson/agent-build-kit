"""`abk review reinstate <class>` lifts a demotion, is the only thing that does, and changes
nothing else (spec: class-demotion, only a person lifts a demotion)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit.cli import main
from agent_build_kit.config import dump
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import demotion_record
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.verdict_record import VERDICTS
from tests import fake_clock
from tests.conftest import make_installation
from tests.factories import new_unit
from tests.review_records import sample_records, write_records

AT = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)


@pytest.fixture
def inst(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Installation:
    installation = make_installation(
        tmp_path / "planning",
        review=dict(enabled=True, classes={"docs": ["docs/**"]}, auto_land=dict(classes=["docs"])),
    )
    (installation.root / "abk.yaml").write_text(dump(installation.config))
    monkeypatch.chdir(installation.root)
    UnitStore(installation.state_dir / "units.json").upsert([new_unit("feature/1")])
    demote(installation, "docs")
    demote(installation, "code")
    return installation


def demote(inst: Installation, unit_class: str) -> None:
    demotion_record.demote(
        inst.state_dir / demotion_record.DEMOTIONS,
        unit_class=unit_class,
        trigger="revert",
        unit="feature/1",
        at=AT,
        say=lambda _: None,
    )


def reinstate(capsys: pytest.CaptureFixture[str], *words: str) -> tuple[int, str]:
    """The exit code of `abk review reinstate <words>` and everything it printed."""
    capsys.readouterr()
    try:
        code = main(["review", "reinstate", *words])
    except SystemExit as stop:
        code = stop.code if isinstance(stop.code, int) else 1
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def recorded(inst: Installation) -> dict[str, dict]:
    return demotion_record.read_demotions(inst.state_dir / demotion_record.DEMOTIONS)


def test_the_demotion_is_lifted_with_the_time_and_reported(
    inst: Installation, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = fake_clock.install(monkeypatch)

    code, output = reinstate(capsys, "docs")

    assert code == 0, output
    assert "docs" in output
    assert datetime.fromisoformat(recorded(inst)["docs"]["lifted"]) == clock.now()
    assert demotion_record.demoted_classes(inst.state_dir / demotion_record.DEMOTIONS) == ("code",)


def test_a_class_that_is_not_demoted_is_refused_and_nothing_changes(
    inst: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    path = inst.state_dir / demotion_record.DEMOTIONS
    before = path.read_bytes()

    code, output = reinstate(capsys, "config")

    assert code != 0
    assert "config" in output and "not demoted" in output
    assert path.read_bytes() == before


def test_a_class_already_lifted_is_refused(
    inst: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    assert reinstate(capsys, "docs")[0] == 0
    lifted = recorded(inst)["docs"]["lifted"]

    code, output = reinstate(capsys, "docs")

    assert code != 0
    assert "not demoted" in output
    assert recorded(inst)["docs"]["lifted"] == lifted


def test_an_unreadable_demotion_file_is_refused_and_left_as_it_is(
    inst: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    path = inst.state_dir / demotion_record.DEMOTIONS
    path.write_text("not json")

    code, output = reinstate(capsys, "docs")

    assert code != 0
    assert demotion_record.DEMOTIONS in output
    assert path.read_text() == "not json"


def test_time_lifts_nothing_and_a_lift_is_for_the_class_named_only(
    inst: Installation, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = fake_clock.install(monkeypatch)
    clock.advance(timedelta(days=30).total_seconds())
    assert recorded(inst)["code"]["lifted"] is None

    assert reinstate(capsys, "docs")[0] == 0

    assert recorded(inst)["code"]["lifted"] is None
    assert datetime.fromisoformat(recorded(inst)["docs"]["lifted"]) == clock.now()


def test_the_command_changes_nothing_but_the_demotion_record(
    inst: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    write_records(inst.state_dir / VERDICTS, sample_records())
    files = [inst.root / "abk.yaml", inst.state_dir / VERDICTS, inst.state_dir / "units.json"]
    before = [f.read_bytes() for f in files]
    others = recorded(inst)["code"]

    assert reinstate(capsys, "docs")[0] == 0

    assert [f.read_bytes() for f in files] == before
    assert recorded(inst)["code"] == others
