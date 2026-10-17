"""The documents say how a prompt reaches the agent (spec: prompt-delivery)."""

from __future__ import annotations

import re
from pathlib import Path

from tests.prompt_text import flat

ROOT = Path(__file__).resolve().parents[2]
RUNTIMES = flat((ROOT / "docs" / "agent-runtimes.md").read_text())
ARCHITECTURE = flat((ROOT / "docs" / "architecture.md").read_text())
CLI = flat((ROOT / "docs" / "cli.md").read_text())


def test_the_runtime_document_names_the_three_transports_and_their_safe_sizes() -> None:
    for transport in ("`argument`", "`stdin`", "`protocol`"):
        assert transport in RUNTIMES
    assert "100,000" in RUNTIMES
    assert "2,000,000" in RUNTIMES


def test_a_wrapper_command_is_told_to_pass_its_standard_input_on() -> None:
    assert re.search(
        r"runtimes\.claude_code\.command[^.]*(must|has to)[^.]*standard input", RUNTIMES
    )


def test_the_planner_call_is_no_longer_described_with_the_prompt_as_an_argument() -> None:
    row = re.search(r"`pipeline/planner\.py` \|(.*?)\| `pipeline/restack\.py`", RUNTIMES)

    assert row
    assert "claude -p" not in row[1]


def test_the_architecture_says_the_planners_list_omits_landed_units_of_other_changes() -> None:
    assert re.search(r"omit[^.]*merged[^.]*other changes|other changes[^.]*omit", ARCHITECTURE)


def test_the_replan_listing_shows_the_failure_of_a_prompt_that_is_too_large() -> None:
    assert re.search(r"failing 1/3: the \S+ prompt( for \S+)? is [\d,]+ bytes", CLI)
