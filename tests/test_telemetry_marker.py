"""The `telemetry_otel` marker is registered and carried by every telemetry-stack test, so a
split can select and hold them (spec: e2e-telemetry-marker)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.config import E2eSplit
from agent_build_kit.pipeline.e2e_exclusive import check_splits
from agent_build_kit.profiles.python_uv import PROFILE
from tests.runtime_tag_collection import ROOT, project_options

MARKER = "telemetry_otel"
MODULE = ROOT / "tests" / "integration" / "test_telemetry_stack.py"
SPLITS = (
    E2eSplit(name="telemetry", marker=MARKER),
    E2eSplit(name="acp", marker="runtime_acp"),
    E2eSplit(name="rest"),
)
COMMAND = [sys.executable, "-m", "pytest", "-m", "local_stack", str(MODULE)]


def run_in_root(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
    return subprocess.run(argv, cwd=ROOT, **kwargs)


def registered_names() -> list[str]:
    return [marker.split(":")[0].strip() for marker in project_options()["markers"]]


def test_the_telemetry_marker_is_registered() -> None:
    assert MARKER in registered_names()


def test_every_test_of_the_telemetry_module_carries_the_marker(pytester: pytest.Pytester) -> None:
    items, _ = pytester.inline_genitems(str(MODULE))

    assert items
    assert [i.nodeid for i in items if i.get_closest_marker(MARKER) is None] == []


def test_a_split_on_the_marker_selects_the_telemetry_tests_and_no_test_is_in_two_splits() -> None:
    result = check_splits(PROFILE, COMMAND, "local_stack", SPLITS, run=run_in_root)
    tests = {listing.name: listing.tests or () for listing in result.listings}

    assert result.findings == ()
    assert tests["telemetry"]
    assert all(Path(test.split("::")[0]).name == MODULE.name for test in tests["telemetry"])
    assert tests["rest"] == ()
