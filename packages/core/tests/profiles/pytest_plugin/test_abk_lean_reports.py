"""The lean-reports plugin drops saved coverage and passing output from the reports testmon keeps.

Each case runs a child pytest in-process with a fake collector registered as testmon's (the
child's sources are files under `tests/child_modules/lean_reports/`).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

PLUGIN = "agent_build_kit.profiles.pytest_plugin.abk_lean_reports"
RUNNING_AS = "ABK_FAKE_TESTMON_RUNNING_AS"


def run_child(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
    running_as: str | None,
    module: str,
    *options: str,
) -> tuple[pytest.RunResult, dict[str, Any]]:
    if running_as is None:
        monkeypatch.delenv(RUNNING_AS, raising=False)
    else:
        monkeypatch.setenv(RUNNING_AS, running_as)
    pytester.copy_example("lean_reports")
    result = pytester.runpytest_inprocess(
        "-p", PLUGIN, "-p", "no:cacheprovider", "-o", "python_functions=child_*", *options, module
    )
    report_file = pytester.path / "reports.json"
    assert report_file.exists(), result.outlines
    return result, json.loads(report_file.read_text())


def teardowns(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for row in data["reports"] if row["when"] == "teardown"]


@pytest.mark.parametrize("running_as", ["single", "controller"])
def test_a_saved_batch_loses_its_coverage_and_a_passing_test_its_output_where_testmon_saves(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, running_as: str
) -> None:
    result, data = run_child(pytester, monkeypatch, running_as, "outcomes.py", "-rfE")

    assert data["saves"], "the fake collector saved nothing"
    assert all(save["saw_coverage"] for save in data["saves"])
    assert not any(row["has_coverage"] for row in teardowns(data))
    unpassed = [row for row in data["reports"] if row["outcome"] != "passed"]
    assert {row["nodeid"].split("::")[-1] for row in unpassed} == {
        "child_fails",
        "child_errors",
        "child_skips",
        "child_xfails",
    }
    assert all(row["sections_after"] == row["sections_when_handled"] for row in unpassed)
    assert any(row["sections_when_handled"] for row in unpassed)
    assert "printed by child_fails" in result.stdout.str()
    passing = [row for row in data["reports"] if row["nodeid"].endswith("::child_passes")]
    assert {row["when"] for row in passing} == {"setup", "call", "teardown"}
    assert any(row["sections_when_handled"] for row in passing)
    assert all(row["sections_after"] == 0 for row in passing)


def test_passed_output_that_is_asked_for_is_kept_and_shown(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, data = run_child(pytester, monkeypatch, "single", "outcomes.py", "-rA")

    passing = [row for row in data["reports"] if row["nodeid"].endswith("::child_passes")]
    assert any(row["sections_when_handled"] for row in passing)
    assert all(row["sections_after"] == row["sections_when_handled"] for row in passing)
    assert "printed by child_passes" in result.stdout.str()


def test_a_failed_save_keeps_the_coverage_and_the_run_ends_in_an_internal_error(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, data = run_child(pytester, monkeypatch, "single", "save_fails.py")

    assert result.ret == pytest.ExitCode.INTERNAL_ERROR
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

    assert result.ret == pytest.ExitCode.OK
    assert any(row["sections_when_handled"] for row in data["reports"])
    assert all(row["sections_after"] == row["sections_when_handled"] for row in data["reports"])
    assert len([line for line in result.outlines if line.startswith("abk_lean_reports:")]) == 1
