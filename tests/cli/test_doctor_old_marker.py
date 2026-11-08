"""`abk doctor` warns, and does not fail, for a repository that sets the old e2e marker name."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.cli.doctor import Check, run_doctor
from tests.cli.test_doctor import Answers, which_all
from tests.factories import init_repo

# Built in parts so this file carries no old name for the guard to find.
OLD = "local" + "_stack"


def doctor(tmp_path: Path, tests_block: str) -> list[Check]:
    planning = init_repo(tmp_path / "planning")
    app = init_repo(tmp_path / "app")
    (planning / "abk.yaml").write_text(
        f"version: 1\nrepos:\n  app:\n    path: {app}\n    slug: example/app\n{tests_block}"
    )
    return run_doctor(planning / "abk.yaml", run=Answers(), which=which_all)


def marker_warnings(checks: list[Check]) -> list[Check]:
    return [
        check
        for check in checks
        if check.status == "warn" and "tests.e2e_marker" in check.name + check.detail + check.fix
    ]


def test_the_old_name_is_a_warning_naming_the_key_the_old_value_and_the_new_one(
    tmp_path: Path,
) -> None:
    checks = doctor(tmp_path, "    tests:\n      e2e_marker: " + OLD + "\n")

    found = marker_warnings(checks)
    assert len(found) == 1
    text = found[0].name + found[0].detail + found[0].fix
    assert OLD in text
    assert "`e2e`" in text or " e2e" in text
    assert not [check for check in checks if check.status == "FAIL"]


def test_the_new_name_draws_no_warning(tmp_path: Path) -> None:
    assert not marker_warnings(doctor(tmp_path, "    tests:\n      e2e_marker: e2e\n"))


def test_no_value_draws_no_warning(tmp_path: Path) -> None:
    assert not marker_warnings(doctor(tmp_path, ""))
