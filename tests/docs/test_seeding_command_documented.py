"""The documents say the Python profile's selection applies selectors such as `-m` together
with the selection (spec: affected-test-selection)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "src" / "agent_build_kit" / "skills" / "abk-config" / "SKILL.md"
SELECTOR_SENTENCE = r"selectors such as -m.{0,80}(together with|alongside).{0,40}selection"


def squashed(path: Path) -> str:
    """The file's text on one line with the code ticks dropped, so a wrapped sentence matches."""
    return " ".join(path.read_text(encoding="utf-8").replace("`", "").split())


def test_the_seeding_command_row_says_selectors_apply_together_with_the_selection() -> None:
    text = squashed(ROOT / "docs" / "toolchain-profiles.md")
    row = text[text.index("seeding_command(command, seed") :]
    assert re.search(SELECTOR_SENTENCE, row[:4000], re.I)


@pytest.mark.parametrize(
    "path", [ROOT / "docs" / "configuration.md", SKILL], ids=["configuration.md", "abk-config"]
)
def test_the_checks_affected_comment_says_selectors_apply_together_with_the_selection(
    path: Path,
) -> None:
    text = squashed(path)
    assert re.search(r"affected: mode: off.{0,3000}" + SELECTOR_SENTENCE, text, re.I | re.S)
