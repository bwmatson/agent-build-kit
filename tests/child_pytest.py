"""Run a scenario folder of `tests/child_modules/` as a child pytest."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

import pytest

from agent_build_kit.model import Frozen
from tests.tracked_files import ROOT


class ChildRun(Frozen):
    code: int
    output: str


def run_scenario(
    pytester: pytest.Pytester,
    scenario: str,
    module: str,
    *args: str,
    env: Mapping[str, str] = {},
    monkeypatch: pytest.MonkeyPatch,
) -> ChildRun:
    """Copy `tests/child_modules/<scenario>` into the test's directory and run `module` there in
    a subprocess with the time-limit plugin loaded."""
    pytester.copy_example(scenario)
    monkeypatch.setenv("PYTHONPATH", str(ROOT))
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    result = pytester.runpytest_subprocess(
        "-p", "tests.time_limit", "-p", "no:cacheprovider", "-q", module, *args
    )
    return ChildRun(code=int(result.ret), output=result.stdout.str() + result.stderr.str())


def collect_items(pytester: pytest.Pytester, *paths: str | Path) -> list[pytest.Item]:
    """Collect repository modules in-process for a test that reads the items. The conftest gives
    every test using it the loaded limit; an inner collection that fails fails the test with the
    collection's report text, never with an empty list."""
    items, reprec = pytester.inline_genitems(*(str(p) for p in paths))
    failed = [r for r in reprec.getreports("pytest_collectreport") if r.failed]
    if failed:
        pytest.fail("\n".join(f"{r.nodeid}\n{r.longreprtext}" for r in failed), pytrace=False)
    return items


def collect_listing(*targets: str) -> ChildRun:
    """The `--collect-only -q` listing of a child pytest run on `targets` (paths below the
    repository root, and any options, such as `-m`, that go with them), so a test of what is
    collected reads a few files, never the whole suite."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
            *targets,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return ChildRun(code=result.returncode, output=result.stdout + result.stderr)
