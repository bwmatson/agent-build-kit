"""The history documents carry a status note and the changelog's unreleased section has an entry
for each change. That no document names a removed key outside the migration is an entry of the
table in `tests/exclusions.py`."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HISTORY = (
    "docs/designs/agent-efficient-coding-philosophy.md",
    "docs/designs/risk-tiered-review-design.md",
)
STATUS = re.compile(r"status\W{0,4}implemented", re.I)


def unreleased() -> list[str]:
    """The bullets of the changelog's unreleased section, each as one line of text."""
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    section = text.split("## Unreleased", 1)[1].split("\n## ", 1)[0]
    return [" ".join(b.split()) for b in re.split(r"\n\s*\n", section) if b.strip()]


def test_the_history_documents_open_with_a_status_note() -> None:
    for name in HISTORY:
        top = "\n".join((ROOT / name).read_text(encoding="utf-8").splitlines()[:8])
        assert STATUS.search(top), name


def test_the_changelog_has_an_entry_for_each_change() -> None:
    entries = unreleased()
    assert any("`review.enabled`" in e and "removed" in e for e in entries)
    assert any("`max_unit_lines`" in e and "no longer accepted" in e for e in entries)
    assert any("never merges" in e and "skills" in e for e in entries)
