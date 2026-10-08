"""The usage endpoint answers what `abk report --json` prints (spec: web-ui)."""

from __future__ import annotations

import json

import httpx
import pytest

from agent_build_kit.cli import main
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.usage_report import GROUPINGS
from tests.ledger_lines import agent_line, fixture_ledger, write_ledger
from tests.serving import seed_pipeline

FILTERS = [
    ({}, []),
    ({"since": "2026-01-02"}, ["--since", "2026-01-02"]),
    ({"change": "feature"}, ["--change", "feature"]),
    ({"unit": "add-marker/2"}, ["--unit", "add-marker/2"]),
    ({"include_estimates": "true"}, ["--include-estimates"]),
]


def cli_report(capsys: pytest.CaptureFixture[str], *argv: str) -> dict:
    capsys.readouterr()
    assert main(["report", *argv, "--json"]) == 0
    return json.loads(capsys.readouterr().out)


@pytest.fixture
def ledger(inst: Installation) -> None:
    seed_pipeline(inst)
    fixture_ledger(inst.state_dir / "usage-ledger.jsonl")


@pytest.mark.usefixtures("ledger")
@pytest.mark.parametrize("by", GROUPINGS)
def test_each_grouping_equals_the_reports(
    api: httpx.Client, capsys: pytest.CaptureFixture[str], by: str
) -> None:
    answer = api.get("/api/usage", params={"by": by})

    assert answer.status_code == 200
    assert answer.json() == cli_report(capsys, "--by", by)


@pytest.mark.usefixtures("ledger")
@pytest.mark.parametrize(("params", "flags"), FILTERS)
def test_each_filter_equals_the_reports(
    api: httpx.Client,
    capsys: pytest.CaptureFixture[str],
    params: dict[str, str],
    flags: list[str],
) -> None:
    answer = api.get("/api/usage", params={"by": "unit", **params})

    assert answer.json() == cli_report(capsys, "--by", "unit", *flags)


@pytest.mark.usefixtures("ledger")
def test_the_grouping_defaults_to_unit_as_the_reports_does(
    api: httpx.Client, capsys: pytest.CaptureFixture[str]
) -> None:
    assert api.get("/api/usage").json() == cli_report(capsys)


@pytest.mark.usefixtures("ledger")
def test_a_grouping_the_report_does_not_know_is_refused(api: httpx.Client) -> None:
    assert api.get("/api/usage", params={"by": "colour"}).status_code in (400, 422)


def test_an_unparsable_last_line_is_skipped(
    inst: Installation, api: httpx.Client, capsys: pytest.CaptureFixture[str]
) -> None:
    seed_pipeline(inst)
    ledger = write_ledger(inst.state_dir / "usage-ledger.jsonl", agent_line())
    with ledger.open("a") as file:
        file.write('{"kind": "agent", "at": "2026-01-02T09:00:00+00:00", "unit": "add-mark')

    answer = api.get("/api/usage", params={"by": "unit"})

    assert answer.status_code == 200
    body = answer.json()
    assert [row["key"] for row in body["rows"]] == ["add-marker/1"]
    assert body["total"]["measured"]["calls"] == 1
    assert body == cli_report(capsys, "--by", "unit")


def test_a_missing_ledger_reports_no_rows(inst: Installation, api: httpx.Client) -> None:
    seed_pipeline(inst)

    answer = api.get("/api/usage", params={"by": "unit"})

    assert answer.status_code == 200
    assert answer.json()["rows"] == []
