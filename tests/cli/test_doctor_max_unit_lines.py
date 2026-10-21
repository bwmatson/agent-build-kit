"""`abk doctor` warns once, and does not fail, for the deprecated `global_limits.max_unit_lines`."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.cli.doctor import Check, run_doctor
from tests.cli.test_doctor import Answers, which_all
from tests.factories import init_repo


def doctor(tmp_path: Path, body: str) -> list[Check]:
    planning = init_repo(tmp_path / "planning")
    (planning / "abk.yaml").write_text(f"version: 1\n{body}")
    return run_doctor(planning / "abk.yaml", run=Answers(), which=which_all)


def test_the_key_is_one_warning_naming_it_and_the_ways_to_move_it(tmp_path: Path) -> None:
    checks = doctor(tmp_path, "global_limits:\n  max_unit_lines: 600\n")

    warned = [
        check
        for check in checks
        if check.status == "warn" and "global_limits.max_unit_lines" in check.detail
    ]
    assert len(warned) == 1
    assert "deprecated" in warned[0].detail
    assert "review.ceilings.full" in warned[0].detail + warned[0].fix
    assert "abk config --migrate" in warned[0].detail + warned[0].fix
    assert [check for check in checks if check.name == "config"][0].status == "ok"


def test_the_absent_key_has_no_warning(tmp_path: Path) -> None:
    noisy = doctor(tmp_path / "set", "global_limits:\n  max_unit_lines: 600\n")
    quiet = doctor(tmp_path / "quiet", "review:\n  ceilings:\n    full: 600\n")

    assert any("max_unit_lines" in check.detail for check in noisy)
    assert [check for check in quiet if check.name == "config"][0].status == "ok"
    assert not [check for check in quiet if "max_unit_lines" in check.detail + check.fix]


def test_the_key_under_the_old_root_key_is_one_warning_for_each_notice(tmp_path: Path) -> None:
    checks = doctor(tmp_path, "limits:\n  max_unit_lines: 600\n")

    warned = [check for check in checks if check.status == "warn"]
    assert len([c for c in warned if "global_limits.max_unit_lines" in c.detail]) == 1
    assert len([c for c in warned if "`limits`" in c.detail]) == 1
