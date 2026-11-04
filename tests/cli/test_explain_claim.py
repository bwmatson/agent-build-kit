"""A skipped start is written as an admission of kind `claim`, and `abk explain` shows it."""

from __future__ import annotations

import argparse
from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_build_kit import trackers
from agent_build_kit.cli.explain_cmd import cmd_explain
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.admission_record import (
    ADMISSIONS_NAME,
    AdmissionRecord,
    read_admissions,
)
from tests.split_start_support import fresh, gate_round, round_ids, store_of
from tests.trackers.start_support import FIRST, PERSON, board_in, taken_by_person

pytestmark = pytest.mark.usefixtures("scripted_engine")


@pytest.fixture(autouse=True)
def stubbed(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    gate_round(monkeypatch)
    yield
    trackers.unregister("azure_devops")


def skipped_unit(tmp_path: Path) -> tuple[Installation, str]:
    """A round that skips FIRST because a person holds its group item; the item's id."""
    world, inst = board_in(tmp_path)
    item_id = taken_by_person(world, "1")
    store = store_of(inst)
    fresh(store, FIRST)
    assert round_ids(inst, store) == []
    return inst, item_id


def claim_records(inst: Installation) -> list[AdmissionRecord]:
    return [
        record
        for record in read_admissions(inst.state_dir / ADMISSIONS_NAME)
        if record.kind == "claim" and record.unit == FIRST
    ]


def test_a_skip_is_written_as_a_claim_admission_with_the_items_outcome_and_reason(
    tmp_path: Path,
) -> None:
    inst, item_id = skipped_unit(tmp_path)

    record = claim_records(inst)[-1]

    assert record.items == (item_id,)
    assert record.outcome == "skip"
    assert PERSON in record.reason


def test_explain_shows_the_skip_the_reason_and_the_item(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inst, item_id = skipped_unit(tmp_path)

    capsys.readouterr()
    assert cmd_explain(argparse.Namespace(unit=FIRST, at=None), inst) == 0
    out = capsys.readouterr().out

    assert "skip" in out
    assert PERSON in out
    assert item_id in out


def test_the_record_holds_the_display_name_and_no_email_address(tmp_path: Path) -> None:
    inst, _ = skipped_unit(tmp_path)

    written = (inst.state_dir / ADMISSIONS_NAME).read_text()

    assert PERSON in written
    assert "@" not in written
