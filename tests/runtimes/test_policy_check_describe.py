"""`policy_check.describe`: a report by class and spelling, or by label when it has no results."""

from __future__ import annotations

from agent_build_kit.runtimes import PolicyReport, policy_check
from tests.runtimes.selectable import amend_finding, spelling_report


def test_a_report_with_results_names_only_the_classes_with_an_open_spelling() -> None:
    assert policy_check.describe(spelling_report()) == amend_finding()


def test_a_report_without_results_gives_its_labels() -> None:
    report = PolicyReport(ok=False, unenforced=("merging a pull request", "amending a commit"))

    assert policy_check.describe(report) == "merging a pull request, amending a commit"
