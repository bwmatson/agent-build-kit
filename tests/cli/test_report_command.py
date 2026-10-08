"""`abk report`: the ledger and the unit store, answered by any grouping as a
table or JSON (spec: usage-reporting)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_build_kit.cli import main
from agent_build_kit.config import dump
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_store import UnitStore
from tests.conftest import make_installation
from tests.factories import unit
from tests.ledger_lines import agent_line, fixture_ledger, write_ledger


@pytest.fixture
def inst(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Installation:
    installation = make_installation(tmp_path / "planning")
    (installation.root / "abk.yaml").write_text(dump(installation.config))
    monkeypatch.chdir(installation.root)
    UnitStore(installation.state_dir / "units.json").upsert(
        [
            unit("add-marker/1"),
            unit("add-marker/2", repo="platform"),
            unit("feature/1", change="feature"),
        ]
    )
    return installation


def run_json(capsys: pytest.CaptureFixture[str], *argv: str) -> dict:
    assert main(["report", *argv, "--json"]) == 0
    return json.loads(capsys.readouterr().out)


def test_report_groups_the_installations_ledger_by_each_grouping(
    inst: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    fixture_ledger(inst.state_dir / "usage-ledger.jsonl")

    for by, count in (("unit", 3), ("change", 2), ("node", 2), ("model", 2), ("day", 3)):
        document = run_json(capsys, "--by", by)

        assert len(document["rows"]) == count, by
        assert document["total"]["measured"]["calls"] == 4


def test_report_defaults_to_a_table_by_unit(
    inst: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    fixture_ledger(inst.state_dir / "usage-ledger.jsonl")

    assert main(["report"]) == 0

    out = capsys.readouterr().out
    assert "add-marker/1" in out
    assert "feature/1" in out
    assert not out.lstrip().startswith("{")


def test_filters_narrow_what_is_reported(
    inst: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    fixture_ledger(inst.state_dir / "usage-ledger.jsonl")

    second_day = "2026-01-02"
    since = run_json(capsys, "--since", second_day)
    change = run_json(capsys, "--change", "feature")
    one_unit = run_json(capsys, "--unit", "add-marker/2")

    assert since["total"]["measured"]["calls"] == 3
    assert [r["key"] for r in change["rows"]] == ["feature/1"]
    assert [r["key"] for r in one_unit["rows"]] == ["add-marker/2"]


def test_estimates_are_left_out_of_totals_unless_asked_for(
    inst: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    write_ledger(
        inst.state_dir / "usage-ledger.jsonl",
        agent_line(),
        agent_line(round=1, session_id="sess-2", input_tokens=1000, usage_source="estimated"),
    )

    plain = run_json(capsys)
    included = run_json(capsys, "--include-estimates")

    assert plain["total"]["measured"]["input_tokens"] == 100
    assert plain["total"]["estimated"]["input_tokens"] == 1000
    assert included["total"]["measured"]["input_tokens"] == 1100


def test_an_empty_ledger_reports_no_rows_and_succeeds(
    inst: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run_json(capsys)["rows"] == []
    assert main(["report"]) == 0
