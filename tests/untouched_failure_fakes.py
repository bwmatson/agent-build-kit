"""Pre-existing failures as the tests of the record, the fix change and the preview build them."""

from __future__ import annotations

from datetime import UTC, datetime

from agent_build_kit.pipeline.untouched_failures import PreExisting

TEST = "tests/far/test_one.py::test_one"
OUTPUT = "FAILED tests/far/test_one.py::test_one - assert 1 == 2\n"


def failing(
    test: str = TEST,
    unit: str = "feature/1",
    *,
    line: str = "assert 1 == 2",
    base_output: str = OUTPUT,
    change: str = "",
) -> PreExisting:
    """A failure of `test` for `unit` that the base run failed too."""
    return PreExisting(
        test=test,
        unit=unit,
        command="uv run pytest -m local_stack -v",
        line=line,
        at=datetime(2026, 3, 1, 9, 30, tzinfo=UTC),
        base_output=base_output,
        change=change,
    )
