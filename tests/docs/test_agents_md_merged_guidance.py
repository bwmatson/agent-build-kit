"""AGENTS.md tells a change to this repo's own pipeline code when to write `Needs: ... merged`."""

from __future__ import annotations

import re
from pathlib import Path

from tests.installation_leaks import leaky_line

ROOT = Path(__file__).resolve().parents[2]
HEADING = "## Code changes go through the spec process"
CODE_AREAS = ("tick", "requeue", "wait-end", "plan", "graph", "build", "usage", "gate")


def section() -> str:
    """The raw text of the spec-process section of AGENTS.md."""
    text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    start = text.index(HEADING)
    end = text.find("\n## ", start + 1)
    return text[start : end if end != -1 else None]


def squashed(text: str) -> str:
    return " ".join(text.replace("`", "").split())


def test_the_section_names_the_merged_line_and_the_code_it_applies_to() -> None:
    text = squashed(section())
    assert re.search(r"Needs: .{0,40}merged", text)
    for area in CODE_AREAS:
        assert re.search(rf"\b{area}\b", text, re.I), area
    assert re.search(r"own (tick|code)", text, re.I)


def test_the_section_gives_the_reason_a_tick_loads_the_code_once() -> None:
    text = squashed(section())
    assert re.search(r"loads? (the kit's|its|this repo's)? ?code once", text, re.I)
    assert re.search(r"start of (the|a) tick|at its start", text, re.I)
    assert re.search(r"merge.{0,200}(next|later) tick", text, re.I)


def test_the_section_has_one_example_needs_line() -> None:
    lines = [
        line
        for line in section().splitlines()
        if re.search(r"Needs: [\w<>-]+ group \d+ merged", line)
    ]
    assert len(lines) == 1


def test_the_added_text_names_no_installation() -> None:
    lines = [line for line in section().splitlines() if "merged" in line or "loads" in line]
    assert lines
    assert [line for line in lines if leaky_line(line)] == []


def test_claude_md_only_loads_agents_md() -> None:
    text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "@AGENTS.md" in text
    assert "merged" not in text
    assert "AGENTS.md" in text and len(text.splitlines()) <= 8
    assert re.search(r"Needs: ", section())
