"""`abk doctor` reports a configured tracker and says nothing about trackers otherwise
(spec: tracker-seam, "doctor and status report a configured tracker and nothing else")."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import trackers
from agent_build_kit.cli.doctor import Check, run_doctor
from agent_build_kit.forges.transport import clear_credentials
from agent_build_kit.trackers.azure_devops import AzureDevOpsWorkItems
from agent_build_kit.trackers.base import Tracker
from agent_build_kit.trackers.config import AzureDevOpsTracker, TrackerSection
from agent_build_kit.trackers.local import LocalTracker
from tests.cli.test_doctor import Answers
from tests.cli.tracker_fakes import (
    IDENTITY,
    INCOMPLETE,
    KIND,
    ORGANIZATION,
    SECTION,
    RefusedTracker,
    planned,
    served,
)
from tests.factories import which_all
from tests.trackers.ado_project import BASIC
from tests.trackers.ado_work_item_host import WorkItemHost


def tracker_checks(config: Path) -> list[Check]:
    return [
        check
        for check in run_doctor(config, run=Answers(), which=which_all)
        # By name: another check's detail may hold a path (the checkout's own) that says "tracker".
        if check.name.lower().startswith("tracker")
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


def test_the_fix_for_a_refused_credential_names_the_variable_only_when_one_is_set(
    tmp_path: Path,
) -> None:
    without = SECTION.replace("      token_env: TRACKER_PAT\n", "")
    (tmp_path / "named").mkdir()
    (tmp_path / "unnamed").mkdir()
    with served(RefusedTracker()):
        (named,) = tracker_checks(planned(tmp_path / "named", SECTION))
        (unnamed,) = tracker_checks(planned(tmp_path / "unnamed", without))

    assert "TRACKER_PAT" in named.fix
    assert "TRACKER_PAT" not in unnamed.fix
    assert "forge's credential" in unnamed.fix


def test_a_valid_section_with_no_implementation_is_not_blamed_on_the_section(
    tmp_path: Path,
) -> None:
    (check,) = tracker_checks(planned(tmp_path, SECTION))

    assert check.status == "warn"
    assert KIND in check.detail
    assert "does not implement" in check.fix
    assert "fix repos.app.tracker" not in check.fix


def test_an_invalid_section_reports_its_error(tmp_path: Path) -> None:
    with served(LocalTracker()):
        (check,) = tracker_checks(planned(tmp_path, INCOMPLETE))

    assert check.status == "FAIL"
    assert "project" in check.detail
    assert "app" in check.detail
    assert "repos.app.tracker" in check.fix


def test_the_probe_of_a_tracker_that_has_one_is_a_check_for_each_of_its_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ABK_ADO_PAT", "pat-secret")  # the run reloads settings from the environment
    clear_credentials()
    host = WorkItemHost(project=BASIC)
    wrong_type = SECTION.replace("      token_env: TRACKER_PAT\n", "").replace(
        "      story_type: User Story\n",
        "      types:\n        change: Issue\n        group: User Story\n",
    )

    def factory(section: TrackerSection) -> Tracker:
        assert isinstance(section, AzureDevOpsTracker)
        return AzureDevOpsWorkItems(section, http=host)

    trackers.register(KIND, factory)
    try:
        checks = tracker_checks(planned(tmp_path, wrong_type))
    finally:
        trackers.unregister(KIND)
        clear_credentials()

    failing = [check for check in checks if check.status == "FAIL"]
    [types] = [check for check in failing if "group" in check.detail]
    assert "User Story" in types.detail
    assert "repos.app.tracker" in types.fix
    assert any(check.status == "ok" and "work item access" in check.detail for check in checks)
    assert "pat-secret" not in " ".join(check.detail for check in checks)


def test_a_repo_with_no_section_adds_no_line(tmp_path: Path) -> None:
    with served():
        assert tracker_checks(planned(tmp_path)) == []
