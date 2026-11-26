"""Child run for the lean-reports plugin's tests: a fake testmon collector and a report log."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

STORED: list[tuple[Any, int]] = []
SAVES: list[dict[str, Any]] = []
RAISES_FOR = "child_save_fails"


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_logreport(report: Any) -> None:
    STORED.append((report, len(report.sections)))


def pytest_unconfigure(config: pytest.Config) -> None:
    rows = [
        {
            "nodeid": report.nodeid,
            "when": report.when,
            "outcome": report.outcome,
            "has_coverage": "nodes_files_lines" in report.__dict__,
            "sections_after": len(report.sections),
            "sections_when_handled": handled,
        }
        for report, handled in STORED
    ]
    target = Path(config.invocation_params.dir) / "reports.json"
    target.write_text(json.dumps({"reports": rows, "saves": SAVES}))


class FakeTestmon:
    def __init__(self, running_as: str) -> None:
        self._running_as = running_as

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(self, item: pytest.Item) -> Any:
        outcome = yield
        report = outcome.get_result()
        if report.when == "teardown":
            report.nodes_files_lines = {item.nodeid: {"m.py": [1]}}

    def pytest_runtest_logreport(self, report: Any) -> None:
        if report.when != "teardown":
            return
        SAVES.append(
            {"nodeid": report.nodeid, "saw_coverage": "nodes_files_lines" in report.__dict__}
        )
        if report.nodeid.endswith(RAISES_FOR):
            raise RuntimeError("the save failed")


def pytest_configure(config: pytest.Config) -> None:
    STORED.clear()
    SAVES.clear()
    running_as = os.environ.get("ABK_FAKE_TESTMON_RUNNING_AS")
    if running_as is not None:
        config.pluginmanager.register(FakeTestmon(running_as), "TestmonCollect")
