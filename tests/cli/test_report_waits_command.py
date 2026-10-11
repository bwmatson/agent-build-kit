"""`abk report --waits`: wall time by cause from the installation's records
(spec: usage-reporting)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_build_kit.cli import main
from agent_build_kit.config import dump
from agent_build_kit.pipeline.usage_report import build_wait_report, render_json
from tests.conftest import make_installation
from tests.wait_fixture import HOUR, Recorded, worked_example


@pytest.fixture
def recorded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Recorded:
    installation = make_installation(tmp_path / "planning")
    (installation.root / "abk.yaml").write_text(dump(installation.config))
    monkeypatch.chdir(installation.root)
    return worked_example(installation.state_dir)


def run_json(capsys: pytest.CaptureFixture[str], *argv: str) -> dict:
    assert main(["report", "--waits", *argv, "--json"]) == 0
    return json.loads(capsys.readouterr().out)


def test_the_json_is_the_waits_report_of_the_installations_records(
    recorded: Recorded, capsys: pytest.CaptureFixture[str]
) -> None:
    document = run_json(capsys)

    expected = build_wait_report(recorded.ledger, recorded.decisions, recorded.units)
    assert document == json.loads(render_json(expected))
    assert len(document["rows"]) == 72
    assert document["total"]["running_agent_ms"] == 41_760_000
    assert document["idle"]["idle_h"] == 47


def test_by_day_regroups_the_same_total(
    recorded: Recorded, capsys: pytest.CaptureFixture[str]
) -> None:
    by_unit = run_json(capsys, "--by", "unit")
    by_day = run_json(capsys, "--by", "day")

    assert by_day["group_by"] == "day"
    assert by_day["total"] == {**by_unit["total"], "key": by_day["total"]["key"]}
    assert sum(r["wall_ms"] for r in by_day["rows"]) == 1608 * HOUR


def test_the_table_is_the_default_and_shows_the_analysis(
    recorded: Recorded, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["report", "--waits"]) == 0

    out = capsys.readouterr().out
    assert not out.lstrip().startswith("{")
    lines = out.splitlines()
    assert "hours: planned 1343.0, in review 172.0, running 93.0 (agent 11.6)" in lines
    assert "nothing ran for 47 of 87 hours: 17 with a full queue, 30 with room" in lines


def test_a_grouping_the_waits_do_not_have_is_refused(
    recorded: Recorded, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["report", "--waits", "--by", "node"]) != 0
