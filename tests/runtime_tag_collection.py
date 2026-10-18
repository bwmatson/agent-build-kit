"""Collecting fixture test files the way the project does, for the runtime-tag tests.

The inner run takes the project's own registered markers and default options (strict
markers among them) and the runtime-tag plugin, so what it collects is what the suite's
collection would make of the same file.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from tests.runtime_tags import runtime_tags

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = "tests.runtime_tags"


def project_options() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["pytest"]["ini_options"]


def collect(pytester: pytest.Pytester, expression: str = "", **files: str) -> pytest.RunResult:
    """Collect the given modules under the project's markers and options, selecting by the
    marker expression (empty: every marker, the default `-m` being replaced)."""
    options = project_options()
    markers = "\n".join(f"    {marker}" for marker in options["markers"])
    pytester.makeini(f"[pytest]\nmarkers =\n{markers}\naddopts = {options['addopts']}\n")
    pytester.makepyfile(**files)
    return pytester.runpytest(
        "-p", PLUGIN, "-p", "no:cacheprovider", "--collect-only", "-q", "-m", expression
    )


def assert_runs_on_claude_code_alone(pytester: pytest.Pytester, module: Path) -> None:
    """Every item `module` collects is a `local_stack` test of the `claude_code` parameter and
    carries the `runtime_claude_code` tag alone."""
    items, _ = pytester.inline_genitems(str(module))

    assert items
    assert [
        (i.nodeid, runtime_tags(i)) for i in items if runtime_tags(i) != ["runtime_claude_code"]
    ] == []
    assert all(i.get_closest_marker("local_stack") is not None for i in items)
    assert all("claude_code" in i.nodeid for i in items)
