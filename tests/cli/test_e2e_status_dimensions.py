"""`abk e2e-test status` and `abk doctor` list each dimension, its values and which are available,
and say nothing about dimensions when none is declared (spec: e2e-dimensions)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent_build_kit.cli.doctor import run_doctor
from tests.cli.e2e_hold_fakes import abk, planning
from tests.cli.test_doctor import Answers
from tests.factories import init_repo, which_all

DECLARED = """\
tests:
  e2e_dimensions:
    runtime:
      acp: {marker: runtime_acp}
      claude_code: {marker: runtime_claude_code}
    telemetry:
      otel: {marker: telemetry_otel}
      local: {marker: telemetry_local}
  e2e_available:
    telemetry: [local]
"""
NONE_DECLARED = "tests:\n  e2e_splits: {}\n"
VALUES = ("acp", "claude_code", "otel", "local")
EXPECTED = {"acp": True, "claude_code": True, "otel": False, "local": True}


def about_dimensions(lines: list[str]) -> list[str]:
    """The parts of `lines` (a line, or a comma-separated part of one) that name a dimension or
    a value of the fixture."""
    parts = [part for line in lines for part in re.split(r"[,;]", line)]
    return [p for p in parts if re.search(rf"\b(runtime|telemetry|{'|'.join(VALUES)})\b", p)]


def availability(lines: list[str]) -> dict[str, bool]:
    """Whether the lines say each value of the fixture is available, by value."""
    found: dict[str, bool] = {}
    for value in VALUES:
        parts = [p for p in about_dimensions(lines) if re.search(rf"\b{value}\b", p)]
        found[value] = any("available" in p and "unavailable" not in p for p in parts)
    return found


def test_status_lists_each_dimension_and_value_with_what_is_available(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for name in ("with", "without"):
        (tmp_path / name).mkdir()
    declared = abk(planning(tmp_path / "with", DECLARED), capsys, "e2e-test", "status")
    without = abk(planning(tmp_path / "without", NONE_DECLARED), capsys, "e2e-test", "status")

    assert declared[0] == 0, declared[2]
    text = "\n".join(declared[1])
    assert "runtime" in text and "telemetry" in text
    assert availability(declared[1]) == EXPECTED
    assert without[0] == 0
    assert about_dimensions(without[1]) == []
    assert "dimension" not in "\n".join(without[1]).lower()


def doctor_lines(tmp_path: Path, tests: str) -> list[str]:
    root = init_repo(tmp_path / "planning")
    (root / "abk.yaml").write_text(f"version: 1\n{tests}")
    checks = run_doctor(root / "abk.yaml", run=Answers(), which=which_all)
    assert not [c for c in checks if c.status in ("warn", "FAIL") and "dimension" in c.detail]
    # Other checks name a runtime or a local path; only one that speaks of availability counts.
    return [f"{c.name}: {c.detail}" for c in checks if "available" in c.detail]


def test_doctor_lists_each_dimension_and_value_with_what_is_available(tmp_path: Path) -> None:
    declared = doctor_lines(tmp_path / "with", DECLARED)
    without = doctor_lines(tmp_path / "without", NONE_DECLARED)

    assert availability(declared) == EXPECTED
    assert about_dimensions(without) == []
