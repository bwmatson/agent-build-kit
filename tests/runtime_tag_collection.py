"""Collecting fixture test files the way the project does, for the runtime-tag tests.

The inner run takes the project's own registered markers and default options (strict
markers among them) and the runtime-tag plugin, so what it collects is what the suite's
collection would make of the same file.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

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
