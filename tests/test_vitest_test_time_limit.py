"""The vitest integration test carries its own time limit (spec: ci-gives-npm-a-longer-timeout).

It downloads vitest at test time, so it is marked `time_limit(180)`; the marker is
registered, so `--strict-markers` accepts it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
VITEST_TEST = ROOT / "tests" / "integration" / "test_node_npm_red_command_vitest.py"


def test_every_vitest_test_carries_time_limit_180(pytester: pytest.Pytester) -> None:
    items, _ = pytester.inline_genitems(
        str(VITEST_TEST),
        "-c",
        str(ROOT / "pyproject.toml"),
        "--strict-markers",
        "-m",
        "integration",
    )

    assert items
    for item in items:
        marker = item.get_closest_marker("time_limit")
        assert marker is not None and marker.args == (180,), item.nodeid
