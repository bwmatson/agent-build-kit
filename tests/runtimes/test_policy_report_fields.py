"""A policy report written before the static check's fields loads with their defaults."""

from __future__ import annotations

from agent_build_kit.runtimes import PolicyReport
from tests.runtimes.policy_static_support import said


def test_a_report_written_without_the_added_fields_loads() -> None:
    written = {
        "ok": False,
        "unenforced": ["amending a commit"],
        "fix": "run it",
        "results": [
            {
                "label": "amending a commit",
                "spelling": "plain",
                "command": "git commit --amend",
                "refused": False,
            }
        ],
    }

    report = PolicyReport.model_validate(written)

    assert said(report, "source") == ""
    assert said(report, "cannot_check") == ""
    assert said(report.results[0], "by") == ""
    assert said(report.results[0], "by_design") is False
    assert report.ok is False


def test_ok_is_unchanged_for_a_report_without_the_fields() -> None:
    report = PolicyReport.model_validate({"ok": True})

    assert report.ok is True
    assert said(report, "cannot_check") == ""
