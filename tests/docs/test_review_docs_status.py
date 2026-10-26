"""The history documents carry a status note, the documents name neither removed key outside the
migration, and the changelog's unreleased section has an entry for each change."""

import re
from pathlib import Path

from tests.repo_docs import repo_markdown

ROOT = Path(__file__).resolve().parents[2]
HISTORY = (
    "docs/designs/agent-efficient-coding-philosophy.md",
    "docs/designs/risk-tiered-review-design.md",
)
RUNBOOK = "docs/runbooks/migrate-to-risk-tiered-review.md"
REMOVED = re.compile(r"review\.enabled|max_unit_lines")
STATUS = re.compile(r"status\W{0,4}implemented", re.I)


def unreleased() -> list[str]:
    """The bullets of the changelog's unreleased section, each as one line of text."""
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    section = text.split("## Unreleased", 1)[1].split("\n## ", 1)[0]
    return [" ".join(b.split()) for b in re.split(r"\n\s*\n", section) if b.strip()]


def documents(root: Path = ROOT) -> list[Path]:
    """Every Markdown file but the changelog, the history documents and the migration runbook."""
    exempt = [ROOT / name for name in (*HISTORY, RUNBOOK)]
    return [path for path in repo_markdown(exempt) if path.name != "CHANGELOG.md"]


def reported(text: str) -> list[str]:
    """The paragraphs of a text that name a removed key without naming the migration command."""
    return [
        paragraph
        for paragraph in re.split(r"\n\s*\n", text)
        if REMOVED.search(paragraph) and "--migrate" not in paragraph
    ]


def test_the_history_documents_open_with_a_status_note() -> None:
    for name in HISTORY:
        top = "\n".join((ROOT / name).read_text(encoding="utf-8").splitlines()[:8])
        assert STATUS.search(top), name


def test_no_document_names_a_removed_key_outside_the_migration() -> None:
    found = [
        path.relative_to(ROOT).as_posix()
        for path in documents()
        if reported(path.read_text(encoding="utf-8"))
    ]
    assert not found, found


def test_a_paragraph_naming_a_removed_key_and_database_migrations_is_reported() -> None:
    text = (
        "`max_unit_lines` is gone.\n\n"
        "The defaults cover migrations, and `max_unit_lines` stays.\n\n"
        "Run `abk config --migrate` for `max_unit_lines`."
    )

    assert len(reported(text)) == 2


def test_the_changelog_has_an_entry_for_each_change() -> None:
    entries = unreleased()
    assert any("`review.enabled`" in e and "removed" in e for e in entries)
    assert any("`max_unit_lines`" in e and "no longer accepted" in e for e in entries)
    assert any("never merges" in e and "skills" in e for e in entries)
