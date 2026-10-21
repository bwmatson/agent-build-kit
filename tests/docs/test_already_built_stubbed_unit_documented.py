"""The documents and the changelog say a stubbed unit with no commit of its own is satisfied."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"


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


def assert_changelog_bullet_once() -> None:
    matching = [
        b
        for b in unreleased_bullets()
        if re.search(r"no commit of its own", b) and re.search(r"missing .{0,30}pair", b)
    ]
    assert len(matching) == 1
    assert re.search(r"satisfied", matching[0])


def test_the_architecture_document_says_a_stubbed_unit_with_no_commit_is_satisfied() -> None:
    text = squashed((DOCS / "architecture.md").read_text(encoding="utf-8"))
    start = text.index("Stubbed build, per group.")
    paragraph = text[start : text.index("Test-only groups.", start)]
    assert re.search(
        r"no commit of its own.{0,300}satisfied|satisfied.{0,300}no commit of its own",
        paragraph,
        re.I,
    )
    assert re.search(
        r"(commits?|pair).{0,200}missing pair.{0,200}stops?|missing pair.{0,200}still stops?",
        paragraph,
        re.I,
    )
    assert_changelog_bullet_once()


def test_the_unit_graph_implement_row_says_a_stubbed_unit_with_nothing_new_is_satisfied() -> None:
    text = (DOCS / "unit-graph.md").read_text(encoding="utf-8")
    row = next(line for line in text.splitlines() if line.startswith("| `implement` |"))
    row = squashed(row)
    assert re.search(r"stubbed.{0,300}unit-test.{0,100}satisfied", row, re.I)
