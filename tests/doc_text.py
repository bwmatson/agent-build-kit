"""Shared helpers for the tests that read the documents and the changelog."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def squashed(text: str) -> str:
    """The text on one line with the code ticks dropped, so a wrapped sentence matches."""
    return " ".join(text.replace("`", "").split())


def unreleased_bullets() -> list[str]:
    """The squashed bullets between `## Unreleased` and the next `## ` heading."""
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    start = text.index("## Unreleased")
    end = text.find("\n## ", start + 1)
    body = text[start : end if end != -1 else None]
    return [squashed(b) for b in re.split(r"\n\s*\n", body) if b.lstrip().startswith("- ")]
