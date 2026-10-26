"""AGENTS.md, the CLI reference and the changelog describe the repo-wide guards, the issue
reference scrub and the suite's `.env` isolation."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def squashed(path: Path) -> str:
    """The file's text on one line with the code ticks dropped, so a wrapped sentence matches."""
    return " ".join(path.read_text(encoding="utf-8").replace("`", "").split())


def section(path: Path, heading: str) -> str:
    """The text under `heading` up to the next heading of the same or a higher level."""
    text = path.read_text(encoding="utf-8")
    level = len(heading) - len(heading.lstrip("#"))
    start = text.index(heading)
    rest = text[start + len(heading) :]
    end = re.search(rf"^#{{1,{level}}} ", rest, re.M)
    return " ".join((rest[: end.start()] if end else rest).replace("`", "").split())


def test_agents_md_says_the_leak_scan_reads_the_specification_folder() -> None:
    text = squashed(ROOT / "AGENTS.md")

    assert re.search(r"leak scan.{0,200}(specification folder|openspec)", text, re.I)
    assert re.search(r"~/.{0,120}not a home path|tilde.{0,120}not a home path", text, re.I)


def test_agents_md_says_the_document_guards_skip_planning_content_through_the_helper() -> None:
    text = squashed(ROOT / "AGENTS.md")

    assert re.search(r"document guards.{0,200}skip.{0,40}planning content", text, re.I)
    assert "tests/tracked_files.py" in text


def test_the_cli_reference_says_scrub_store_replaces_references() -> None:
    text = section(ROOT / "docs" / "cli.md", "### `abk scrub-store [--apply]`")

    assert re.search(r"issue|pull-request|pull request", text, re.I)
    assert "<ref>" in text


def test_the_changelog_has_an_unreleased_entry_for_the_guards() -> None:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    unreleased = text.split("## Unreleased", 1)[1].split("\n## ", 1)[0]
    flat = " ".join(unreleased.replace("`", "").split())

    assert "tracked_files" in flat
    assert ".env" in flat
    assert "scrub-store" in flat
