"""`abk doctor` checks `global_limits.max_concurrent_unit_tests` (spec: unit-test-concurrency): an
informational line when it is not set, a warning when it is above the units that can build in a
project, nothing when it is set sensibly in `abk.local.yaml`, and never a failed run. That it is
a machine setting, warned about in a tracked `abk.yaml`, is in test_doctor_machine_keys_table."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_build_kit.cli.doctor import UNIT_TEST_SLOTS, Check, run_doctor
from tests.cli.public_content_repo import committed_config
from tests.cli.test_doctor import Answers
from tests.factories import which_all


def slot_checks(tmp_path: Path, overlay: dict[str, Any]) -> list[Check]:
    config = committed_config(tmp_path / "plan", {}, overlay=overlay)
    checks = run_doctor(config, run=Answers(), which=which_all)
    return [check for check in checks if check.name == UNIT_TEST_SLOTS]


def limit(cap: int | None, stacks: int = 4) -> dict[str, Any]:
    return {
        "global_limits": {"max_concurrent_unit_tests": cap},
        "project_limits": {"max_concurrent_stacks": stacks},
    }


def test_not_set_shows_an_informational_line_that_runs_are_not_limited(tmp_path: Path) -> None:
    [found] = slot_checks(tmp_path, limit(None))

    assert found.status == "info"
    assert "not limited" in found.detail
    assert "abk.local.yaml" in found.fix


def test_a_sensible_value_in_the_local_file_says_nothing(tmp_path: Path) -> None:
    assert slot_checks(tmp_path, limit(2)) == []


def test_a_value_equal_to_the_stacks_says_nothing(tmp_path: Path) -> None:
    assert slot_checks(tmp_path, limit(4, stacks=4)) == []


def test_a_value_above_the_stacks_warns_naming_both(tmp_path: Path) -> None:
    [found] = slot_checks(tmp_path, limit(4, stacks=2))

    assert found.status == "warn"
    assert "max_concurrent_unit_tests" in found.detail and "max_concurrent_stacks" in found.detail
    assert "4" in found.detail and "2" in found.detail


def test_no_result_fails_the_run(tmp_path: Path) -> None:
    for overlay in (limit(None), limit(2), limit(9, stacks=2)):
        assert all(
            found.status != "FAIL" for found in slot_checks(tmp_path / str(overlay), overlay)
        )
