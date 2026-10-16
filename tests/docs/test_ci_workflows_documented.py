"""AGENTS.md has the "CI workflows" section the workflow guard's failure message points at."""

from __future__ import annotations

import re
from pathlib import Path

from tests.ci_workflows import POINTER, RUNNER

AGENTS = Path(__file__).resolve().parents[2] / "AGENTS.md"
HEADING = POINTER.removeprefix("see AGENTS.md, ")


def section() -> str:
    pattern = rf"^#+ {re.escape(HEADING)}\s*$(.*?)(?=^#+ |\Z)"
    match = re.search(pattern, AGENTS.read_text(), re.MULTILINE | re.DOTALL)
    assert match, f"AGENTS.md has no heading {HEADING!r}"
    return match.group(1)


def test_the_guards_message_points_at_the_heading_of_the_section() -> None:
    assert section().strip()


def test_the_section_names_the_table_the_exact_tag_rule_and_the_runner_pin() -> None:
    body = section()

    assert "tests/test_ci_workflows.py" in body
    assert "vX.Y.Z" in body
    assert RUNNER in body
