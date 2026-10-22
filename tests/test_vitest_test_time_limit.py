"""The vitest integration test carries its own time limit (spec: ci-gives-npm-a-longer-timeout).

It downloads vitest at test time, so it is marked `time_limit(180)`; the marker is
registered, so `--strict-markers` accepts it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
VITEST_TEST = ROOT / "tests" / "integration" / "test_node_npm_red_command_vitest.py"


class Collected:
    def __init__(self) -> None:
        self.limits: list[tuple[str, tuple]] = []

    def pytest_collection_modifyitems(self, items: list[pytest.Item]) -> None:
        for item in items:
            marker = item.get_closest_marker("time_limit")
            self.limits.append((item.name, marker.args if marker else ()))


def collect() -> tuple[int, Collected]:
    collected = Collected()
    code = pytest.main(
        [
            str(VITEST_TEST),
            "--collect-only",
            "-q",
            "--strict-markers",
            "-m",
            "integration",
            "-p",
            "no:cacheprovider",
        ],
        plugins=[collected],
    )
    return int(code), collected


def test_every_vitest_test_carries_time_limit_180() -> None:
    code, collected = collect()

    assert code == 0
    assert collected.limits
    for name, args in collected.limits:
        assert args == (180,), name
