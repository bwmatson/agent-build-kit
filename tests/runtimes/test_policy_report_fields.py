"""A policy report written before the static check's fields loads with their defaults."""

from __future__ import annotations

from agent_build_kit.runtimes import PolicyReport


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

    assert report.source == ""
    assert report.cannot_check == ""
    assert report.results[0].by == ""
    assert report.results[0].by_design is False
    assert report.ok is False


def test_ok_is_unchanged_for_a_report_without_the_fields() -> None:
    report = PolicyReport.model_validate({"ok": True})

    assert report.ok is True
    assert report.cannot_check == ""
