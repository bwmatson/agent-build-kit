"""`abk doctor` reports a configured tracker and says nothing about trackers otherwise
(spec: tracker-seam, "doctor and status report a configured tracker and nothing else")."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.cli.doctor import Check, run_doctor
from agent_build_kit.trackers.local import LocalTracker
from tests.cli.test_doctor import Answers
from tests.cli.tracker_fakes import (
    IDENTITY,
    INCOMPLETE,
    ORGANIZATION,
    SECTION,
    RefusedTracker,
    planned,
    served,
)
from tests.factories import which_all


def tracker_checks(config: Path) -> list[Check]:
    return [
        check
        for check in run_doctor(config, run=Answers(), which=which_all)
        if "tracker" in check.name.lower() or "tracker" in check.detail.lower()
    ]


def test_a_valid_section_reports_the_target_and_the_identity(tmp_path: Path) -> None:
    with served():
        (check,) = tracker_checks(planned(tmp_path, SECTION))

    assert check.status == "ok"
    assert ORGANIZATION in check.detail
    assert IDENTITY in check.detail


def test_a_refused_credential_is_one_warning_naming_the_cause(tmp_path: Path) -> None:
    with served(RefusedTracker()):
        (check,) = tracker_checks(planned(tmp_path, SECTION))

    assert check.status == "warn"
    assert ORGANIZATION in check.detail
    assert "refused" in check.detail
    assert check.fix


def test_an_invalid_section_reports_its_error(tmp_path: Path) -> None:
    with served(LocalTracker()):
        (check,) = tracker_checks(planned(tmp_path, INCOMPLETE))

    assert check.status != "ok"
    assert "project" in check.detail
    assert "app" in check.detail


def test_a_repo_with_no_section_adds_no_line(tmp_path: Path) -> None:
    with served():
        assert tracker_checks(planned(tmp_path)) == []
