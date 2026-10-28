"""Run a scenario folder of `tests/child_modules/` as a child pytest."""

from __future__ import annotations

from collections.abc import Mapping

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


def collect_listing(*targets: str) -> ChildRun:
    """The `--collect-only -q` listing of a child pytest run on `targets` (paths below the
    repository root), so a test of what is collected reads a few files, never the whole suite."""
    raise NotImplementedError
