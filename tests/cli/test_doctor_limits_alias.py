"""`abk doctor` warns, and does not fail, for a configuration that uses `limits`."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.cli.doctor import Check, run_doctor
from tests.cli.test_doctor import Answers, which_all
from tests.factories import init_repo


def doctor(tmp_path: Path, key: str) -> list[Check]:
    planning = init_repo(tmp_path / "planning")
    (planning / "abk.yaml").write_text(f"version: 1\n{key}:\n  max_review_rounds: 5\n")
    return run_doctor(planning / "abk.yaml", run=Answers(), which=which_all)


def test_the_old_key_is_a_warning_naming_the_key_and_the_command_and_no_failure(
    tmp_path: Path,
) -> None:
    checks = doctor(tmp_path, "limits")

    warned = [check for check in checks if check.status == "warn" and "limits" in check.detail]
    assert len(warned) == 1
    assert "deprecated" in warned[0].detail
    assert "abk config --migrate" in warned[0].detail + warned[0].fix
    assert [check for check in checks if check.name == "config"][0].status == "ok"


def test_the_new_key_has_no_warning(tmp_path: Path) -> None:
    checks = doctor(tmp_path, "global_limits")

    assert [check for check in checks if check.name == "config"][0].status == "ok"
    assert not [check for check in checks if "deprecated" in check.detail + check.fix]
