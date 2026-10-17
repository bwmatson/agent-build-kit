"""The documents say how a live test is written and what a failed one prints."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def unreleased() -> str:
    changelog = (ROOT / "CHANGELOG.md").read_text()
    return re.split(r"^## ", changelog, flags=re.MULTILINE)[1]


def test_the_architecture_names_the_helper_the_section_its_caps_and_its_place_in_the_log() -> None:
    text = (ROOT / "docs" / "architecture.md").read_text()

    assert "tests/scratch_tick.py" in text
    assert "SCRATCH STATE" in text
    for cap in (r"6000", r"20[ ,]?480", r"61[ ,]?440"):
        assert re.search(cap, text), cap
    assert re.search(r"full output", text, re.IGNORECASE)


def test_agents_tells_a_new_live_test_to_use_the_shared_tick_and_the_guarded_branch_check() -> None:
    text = (ROOT / "AGENTS.md").read_text()

    assert "tests/scratch_tick.py" in text
    assert "commits_on_unit_branch" in text
    assert "register_scratch" in text


def test_the_changelog_entry_names_the_section_and_the_cli_shows_the_unit_lines() -> None:
    assert "SCRATCH STATE" in unreleased()
    cli = (ROOT / "docs" / "cli.md").read_text()
    assert "nothing ready to build" in cli
    assert "(+M more)" in cli
    assert "waits on" in cli
