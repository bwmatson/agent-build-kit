"""`abk doctor` fails a bad `emergency_extra` as a configuration failure and adds nothing for a
valid one."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.cli.doctor import Check, run_doctor
from tests.cli.test_doctor import Answers, which_all
from tests.factories import init_repo


def doctor(tmp_path: Path, block: str) -> list[Check]:
    planning = init_repo(tmp_path / "planning")
    (planning / "abk.yaml").write_text(f"version: 1\nproject_limits:\n{block}")
    return run_doctor(planning / "abk.yaml", run=Answers(), which=which_all)


def test_a_negative_value_is_the_configuration_failure_naming_the_setting(
    tmp_path: Path,
) -> None:
    checks = doctor(tmp_path, "  emergency_extra: -1\n")

    failed = [check for check in checks if check.name == "config"]
    assert [check.status for check in failed] == ["fail"]
    assert "project_limits.emergency_extra" in failed[0].detail
    assert "Extra inputs" not in failed[0].detail


def test_a_valid_value_adds_no_check_of_its_own(tmp_path: Path) -> None:
    absent = doctor(tmp_path / "absent", "  max_units_in_progress: 5\n")

    assert [check for check in absent if check.name == "config"][0].status == "ok"
    for value in ("0", "1"):
        checks = doctor(tmp_path / value, f"  emergency_extra: {value}\n")
        assert [(check.name, check.status) for check in checks] == [
            (check.name, check.status) for check in absent
        ]
        assert not [check for check in checks if "emergency" in check.detail + check.fix]
