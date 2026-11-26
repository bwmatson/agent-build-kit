"""The lean-reports plugin drops saved coverage and passing output from the reports testmon keeps.

Each case runs a child pytest with a fake collector registered as testmon's (the child's
sources are files under `tests/child_modules/lean_reports/`).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.child_pytest import ChildRun, run_scenario

PLUGIN = "agent_build_kit.profiles.pytest_plugin.abk_lean_reports"
RUNNING_AS = "ABK_FAKE_TESTMON_RUNNING_AS"


def run_child(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
    running_as: str | None,
    module: str,
    *options: str,
) -> tuple[ChildRun, dict[str, Any]]:
    monkeypatch.delenv(RUNNING_AS, raising=False)
    result = run_scenario(
        pytester,
        "lean_reports",
        module,
        "-p",
        PLUGIN,
        "-o",
        "python_functions=child_*",
        *options,
        env={RUNNING_AS: running_as} if running_as else {},
        monkeypatch=monkeypatch,
    )
    report_file = pytester.path / "reports.json"
    assert report_file.exists(), result.output
    return result, json.loads(report_file.read_text())


def teardowns(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for row in data["reports"] if row["when"] == "teardown"]


def rows_of(data: dict[str, Any], name: str) -> list[dict[str, Any]]:
    return [row for row in data["reports"] if row["nodeid"].endswith(f"::{name}")]


@pytest.mark.parametrize("running_as", ["single", "controller"])
def test_a_saved_batch_loses_its_coverage_where_testmon_saves(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, running_as: str
) -> None:
    _, data = run_child(pytester, monkeypatch, running_as, "outcomes.py", "-rfE")

    assert data["saves"], "the fake collector saved nothing"
    assert all(save["saw_coverage"] for save in data["saves"])
    assert teardowns(data)
    assert not any(row["has_coverage"] for row in teardowns(data))


@pytest.mark.parametrize("running_as", ["single", "controller"])
def test_a_passing_test_loses_its_output_and_a_test_that_did_not_pass_keeps_it(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, running_as: str
) -> None:
    result, data = run_child(pytester, monkeypatch, running_as, "outcomes.py", "-rfE")

    unpassed = [row for row in data["reports"] if row["outcome"] != "passed"]
    assert {row["nodeid"].split("::")[-1] for row in unpassed} == {
        "child_fails",
        "child_errors",
        "child_skips",
        "child_xfails",
    }
    assert all(row["sections_after"] == row["sections_when_handled"] for row in unpassed)
    assert any(row["sections_when_handled"] for row in unpassed)
    assert "printed by child_fails" in result.output
    passing = rows_of(data, "child_passes")
    assert {row["when"] for row in passing} == {"setup", "call", "teardown"}
    assert any(row["sections_when_handled"] for row in passing)
    assert all(row["sections_after"] == 0 for row in passing)


def test_an_unexpectedly_passing_xfail_keeps_its_output(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, data = run_child(pytester, monkeypatch, "single", "outcomes.py")

    # Only the call report carries `wasxfail`; the others are ordinary passing reports.
    (call,) = [row for row in rows_of(data, "child_xpasses") if row["when"] == "call"]
    assert call["sections_when_handled"]
    assert call["sections_after"] == call["sections_when_handled"]


def test_passed_output_that_is_asked_for_is_kept_and_shown(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, data = run_child(pytester, monkeypatch, "single", "outcomes.py", "-rA")

    passing = rows_of(data, "child_passes")
    assert any(row["sections_when_handled"] for row in passing)
    assert all(row["sections_after"] == row["sections_when_handled"] for row in passing)
    assert "printed by child_passes" in result.output


def test_a_failed_save_keeps_the_coverage_and_the_run_ends_in_an_internal_error(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, data = run_child(pytester, monkeypatch, "single", "save_fails.py")

    assert result.code == int(pytest.ExitCode.INTERNAL_ERROR)
    assert [row["has_coverage"] for row in teardowns(data)] == [True]


def test_a_worker_keeps_every_coverage_and_every_section(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, data = run_child(pytester, monkeypatch, "worker", "outcomes.py")

    assert teardowns(data)
    assert all(row["has_coverage"] for row in teardowns(data))
    assert any(row["sections_when_handled"] for row in data["reports"])
    assert all(row["sections_after"] == row["sections_when_handled"] for row in data["reports"])


def test_without_a_testmon_collector_nothing_changes_and_the_plugin_says_so_once(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, data = run_child(pytester, monkeypatch, None, "passing.py")

    assert result.code == int(pytest.ExitCode.OK)
    assert any(row["sections_when_handled"] for row in data["reports"])
    assert all(row["sections_after"] == row["sections_when_handled"] for row in data["reports"])
    assert (
        len([line for line in result.output.splitlines() if line.startswith("abk_lean_reports:")])
        == 1
    )
