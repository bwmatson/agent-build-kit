"""Keep a recording run's reports small: drop what pytest-testmon has already saved.

Written against pytest-testmon 2.4.0. Its collector registers as ``TestmonCollect`` with
``_running_as`` of ``"single"``, ``"controller"`` or ``"worker"``. It sets
``nodes_files_lines`` on every teardown report, and its plain ``pytest_runtest_logreport``
saves a batch's coverage before it returns. This plugin's ``pytest_runtest_logreport`` is a
wrapper, so the code after its ``yield`` runs after testmon's save and after the terminal
reporter and JUnit XML have read the report. Then the saved coverage and a passing report's
captured output are dropped, so the controller's memory stays flat.

Dropping a report's output frees it only where the report is a copy: on an xdist controller.
Without xdist, pytest keeps the same strings on the item, so only the coverage drop saves
memory there. The wrapper is the old-style ``hookwrapper`` so it loads on any pytest 7 or 8.
On a worker, testmon's collector reports ``_running_as == "worker"`` and the plugin does
nothing.

This module imports only the standard library and pytest: it is loaded by its bare name in a
target repository's environment, where ``agent_build_kit`` is not installed.
"""

from __future__ import annotations

from typing import Any

import pytest

COLLECTOR = "TestmonCollect"
KEEPING_CHARS = frozenset("PXA")


class LeanReports:
    def __init__(self, config: pytest.Config) -> None:
        self._config = config
        self._said = False

    def _recording_here(self) -> bool:
        collector = self._config.pluginmanager.get_plugin(COLLECTOR)
        if collector is None:
            return self._say("no testmon collector is registered")
        running_as = getattr(collector, "_running_as", None)
        if running_as is None:
            return self._say("the testmon collector has no _running_as")
        return running_as in ("single", "controller")

    def _say(self, missing: str) -> bool:
        if not self._said:
            self._said = True
            reporter = self._config.pluginmanager.get_plugin("terminalreporter")
            if reporter is not None:
                reporter.write_line(f"abk_lean_reports: {missing}; reports are kept as they are")
        return False

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_logreport(self, report: Any) -> Any:
        outcome = yield
        if outcome.excinfo is not None or not self._recording_here():
            return
        if report.when == "teardown":
            report.__dict__.pop("nodes_files_lines", None)
        keeps_output = KEEPING_CHARS & set(self._config.option.reportchars or "")
        if report.passed and not hasattr(report, "wasxfail") and not keeps_output:
            report.sections = []


def pytest_configure(config: pytest.Config) -> None:
    config.pluginmanager.register(LeanReports(config), "abk_lean_reports_object")
