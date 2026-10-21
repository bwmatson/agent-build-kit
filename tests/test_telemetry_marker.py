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
from tests.runtime_tag_collection import ROOT

MARKER = "telemetry_otel"
MODULE = ROOT / "tests" / "integration" / "test_telemetry_stack.py"
SPLITS = (
    E2eSplit(name="telemetry", marker=MARKER),
    E2eSplit(name="rest"),
)
COMMAND = [sys.executable, "-m", "pytest", "-m", "local_stack", "tests/integration"]


def run_in_root(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
    return subprocess.run(argv, cwd=ROOT, **kwargs)


def test_every_otel_item_of_the_telemetry_module_carries_the_marker_and_no_other_does(
    pytester: pytest.Pytester,
) -> None:
    items, _ = pytester.inline_genitems(str(MODULE))

    otel = [i for i in items if i.nodeid.endswith("-otel]")]
    assert otel
    assert [i.nodeid for i in otel if i.get_closest_marker(MARKER) is None] == []
    assert [i.nodeid for i in items if i not in otel and i.get_closest_marker(MARKER)] == []


def test_a_split_on_the_marker_selects_the_otel_items_and_no_other_live_test(
    pytester: pytest.Pytester,
) -> None:
    items, _ = pytester.inline_genitems(str(MODULE))
    module_tests = {item.nodeid.split("/")[-1] for item in items if item.nodeid.endswith("-otel]")}

    result = check_splits(PROFILE, COMMAND, "local_stack", SPLITS, run=run_in_root)
    tests = {listing.name: listing.tests or () for listing in result.listings}

    assert result.findings == ()
    assert tests["telemetry"]
    assert {test.split("/")[-1] for test in tests["telemetry"]} == module_tests
    assert tests["rest"]
    assert [
        t for t in tests["rest"] if Path(t.split("::")[0]).name == MODULE.name and "-otel]" in t
    ] == []
