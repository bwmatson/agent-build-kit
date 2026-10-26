"""Shared helpers for the tests that read the documents and the changelog."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def squashed(text: str) -> str:
    """The text on one line with the code ticks dropped, so a wrapped sentence matches."""
    return " ".join(text.replace("`", "").split())


def entry() -> str:
    """The `abk planning split` entry of the command reference, up to the next heading."""
    text = (ROOT / "docs" / "cli.md").read_text()
    start = text.index("### `abk planning split")
    following = re.search(r"^#{1,3} ", text[start + 4 :], re.M)
    return squashed(text[start : start + 4 + following.start() if following else None])


def runbook_step(number: int) -> str:
    """One numbered `## N.` section of the move runbook."""
    text = (ROOT / "docs" / "runbooks" / "move-agent-build-kit-planning.md").read_text()
    match = re.search(rf"^## {number}\. .*?(?=^## \d+\. |\Z)", text, re.M | re.S)
    assert match, f"step {number} not found"
    return squashed(match.group(0))


def unreleased_bullets() -> list[str]:
    """The squashed bullets between `## Unreleased` and the next `## ` heading."""
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    start = text.index("## Unreleased")
    end = text.find("\n## ", start + 1)
    body = text[start : end if end != -1 else None]
    return [squashed(b) for b in re.split(r"\n\s*\n", body) if b.lstrip().startswith("- ")]
