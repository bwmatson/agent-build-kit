"""A failing tier 2 leaves the tail of its output in the unit's run log, with
the node's prefix, besides the words "tier 2 failed" (docs/unit-graph.md)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.e2e import Tier2Result, build_snapshot
from tests.tier2_failure_fakes import run_failing_tier2

TAIL = [
    "FAILED tests/live/test_route.py::test_it - the route 404s",
    "1 failed, 3 passed",
]
FAILURE = build_snapshot(
    Tier2Result(
        sha="abcdef1234567",
        passed=3,
        failed=1,
        skipped=0,
        duration_seconds=1.5,
        command="uv run pytest -m local_stack",
        output="\n".join([*(f"line {n}" for n in range(1, 60)), *TAIL]),
    )
)


def test_a_failing_tier_two_writes_the_tail_of_its_output_to_the_run_log(tmp_path: Path) -> None:
    _, logs = run_failing_tier2(tmp_path, FAILURE)

    (written,) = logs.iterdir()
    lines = written.read_text().splitlines()
    assert any("tier2: stopping: tier 2 failed" in line for line in lines), "\n".join(lines)
    for output_line in TAIL:
        assert any("tier2:" in line and output_line in line for line in lines), (
            f"{output_line!r} is not in the run log:\n" + "\n".join(lines)
        )
    assert not any("tier2:" in line and line.endswith("line 1") for line in lines), (
        "the head of the output is in the run log:\n" + "\n".join(lines)
    )
