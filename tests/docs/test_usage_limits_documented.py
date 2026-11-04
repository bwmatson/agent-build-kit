"""The documents show `usage_limits` as the key of a runtime's and an account's usage windows, and
name the rename, the deprecation of `limits` and `abk config --migrate` (spec: usage-limits-key)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.prompt_text import flat

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"
CONFIGURATION = ROOT / "docs" / "configuration.md"
SECOND_ACCOUNT = ROOT / "docs" / "claude-code-second-account.md"
ARCHITECTURE = ROOT / "docs" / "architecture.md"
CLI = ROOT / "docs" / "cli.md"
SKILLS = ROOT / "src" / "agent_build_kit" / "skills"
SKILL = SKILLS / "abk-config" / "SKILL.md"
EXAMPLES = [README, CONFIGURATION, SECOND_ACCOUNT]
NAMING_THE_RENAME = [CONFIGURATION, ARCHITECTURE, CLI, SKILL]
ALL_DOCUMENTS = [
    README,
    *sorted((ROOT / "docs").glob("*.md")),
    *sorted(SKILLS.glob("*/SKILL.md")),
]
OLD_SPELLING = re.compile(r"runtimes\.[\w<>]+\.(accounts\.[\w<>]+\.)?limits\b")
OLD_KEY_LINE = re.compile(r"^\s*limits:")
RENAME_WORDS = re.compile(r"renamed|deprecated|old name|old spelling", re.IGNORECASE)
RENAME_SENTENCE = re.compile(
    r"(renamed|deprecated).{0,200}usage_limits|usage_limits.{0,200}(renamed|deprecated)",
    re.IGNORECASE,
)
MIGRATION_SENTENCE = re.compile(
    r"usage_limits.{0,400}abk config --migrate|abk config --migrate.{0,400}usage_limits"
)


def paragraphs(path: Path) -> list[str]:
    return [flat(p) for p in re.split(r"\n\s*\n", path.read_text(encoding="utf-8"))]


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_the_examples_use_usage_limits(path: Path) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()

    assert any(line.strip().startswith("usage_limits:") for line in lines)
    assert not [line for line in lines if OLD_KEY_LINE.match(line)]


@pytest.mark.parametrize("path", NAMING_THE_RENAME, ids=lambda p: p.name)
def test_the_document_names_the_rename_the_deprecation_and_the_migration(path: Path) -> None:
    text = flat(path.read_text(encoding="utf-8").replace("`", ""))

    assert RENAME_SENTENCE.search(text), path.name
    assert MIGRATION_SENTENCE.search(text), path.name


def test_no_document_shows_the_old_spelling_as_the_current_one() -> None:
    current = {}
    for path in ALL_DOCUMENTS:
        shown = [
            p
            for p in paragraphs(path)
            if OLD_SPELLING.search(p) and not (RENAME_WORDS.search(p) and "usage_limits" in p)
        ]
        shown += [
            line
            for line in path.read_text(encoding="utf-8").splitlines()
            if OLD_KEY_LINE.match(line)
        ]
        if shown:
            current[str(path.relative_to(ROOT))] = shown

    assert not current, current
