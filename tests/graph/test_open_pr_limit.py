"""The step that opens a pull request builds its body for the unit's forge.

A long tier 2 report must not cost a built unit its pull request: the body
handed to the forge is already within what the repo's host accepts.
"""

from __future__ import annotations

from pathlib import Path

from tests.graph.test_build_path import build
from tests.graph.test_remaining_paths import capturing, fresh
from tests.pipeline.test_pr_body_hosts import AZURE, repo_with


def long_report() -> str:
    lines = "\n".join(f"output line {number:04d} " + "o" * 40 for number in range(150))
    return (
        "## Tier 2 results\n\n- **Result:** 2 passed, 0 failed\n\n"
        f"<details>\n<summary>Full output</summary>\n\n```\n{lines}\n```\n\n</details>\n"
    )


def test_a_long_tier_two_report_reaches_the_forge_within_its_limit(tmp_path: Path) -> None:
    repo_with(**AZURE)  # a host that takes four thousand characters
    recorder = fresh(tmp_path, tier="tier2")
    recorder.tier2_output = long_report()
    assert len(recorder.tier2_output) > 4_000
    bodies: list[dict[str, str]] = []

    build(tmp_path, recorder, open_pr=capturing(recorder, bodies))

    assert bodies
    for opened in bodies:
        assert len(opened["body"]) <= 4_000
        assert len(opened["stacked_body"]) <= 4_000
        assert "2 passed, 0 failed" in opened["body"]
