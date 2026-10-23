"""`abk review report` prints the rates, counts and gates of each class and changes nothing
(spec: review-outcomes)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent_build_kit.cli import main
from agent_build_kit.config import dump
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.verdict_record import VERDICTS
from tests.conftest import make_installation
from tests.factories import new_unit
from tests.review_records import sample_records, write_records


@pytest.fixture
def inst(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Installation:
    installation = make_installation(
        tmp_path / "planning",
        review=dict(
            enabled=True,
            classes={"docs": ["docs/**"], "code": ["src/**"]},
            auto_land=dict(min_samples=3, min_clean_rate=0.9),
        ),
    )
    (installation.root / "abk.yaml").write_text(dump(installation.config))
    monkeypatch.chdir(installation.root)
    UnitStore(installation.state_dir / "units.json").upsert([new_unit("feature/1")])
    return installation


def report(capsys: pytest.CaptureFixture[str]) -> str:
    capsys.readouterr()
    assert main(["review", "report"]) == 0
    return capsys.readouterr().out


def line_of(output: str, name: str) -> str:
    return next(line for line in output.splitlines() if re.search(rf"\b{re.escape(name)}\b", line))


def test_each_class_is_printed_with_its_figures(
    inst: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    write_records(inst.state_dir / VERDICTS, sample_records())

    docs = line_of(report(capsys), "docs")

    # Three samples, all clean, two of them with evidence tier `auto`; two records lack the brief.
    assert re.search(r"\b3\b", docs)
    assert re.search(r"1\.00|100%", docs)
    assert re.search(r"\b2\b.*\bexcluded|\bexcluded\D*\b2\b", docs)


def test_it_says_which_classes_clear_the_gates_and_may_be_listed(
    inst: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    write_records(inst.state_dir / VERDICTS, sample_records())

    output = report(capsys)

    assert re.search(r"\bclears\b", line_of(output, "docs"))
    assert not re.search(r"\bclears\b", line_of(output, "code"))
    assert "review.auto_land.classes" in output


def test_a_class_no_policy_names_is_shown_and_not_offered(
    inst: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    write_records(inst.state_dir / VERDICTS, sample_records())

    line = line_of(report(capsys), "app/unit-test")

    assert "nameable" in line
    assert not re.search(r"\bclears\b", line)


def test_no_records_says_there_is_nothing_to_report(
    inst: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    assert "nothing to report" in report(capsys).lower()


def test_the_report_leaves_the_config_the_records_and_the_units_as_they_were(
    inst: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    write_records(inst.state_dir / VERDICTS, sample_records())
    files = [inst.root / "abk.yaml", inst.state_dir / VERDICTS, inst.state_dir / "units.json"]
    before = [f.read_bytes() for f in files]

    report(capsys)

    assert [f.read_bytes() for f in files] == before
