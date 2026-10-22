"""`docs/cli.md` documents the migration of open changes, in order, and the changelog's
unreleased section has one entry naming its commands.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.prompt_text import flat

ROOT = Path(__file__).resolve().parents[2]
CLI = (ROOT / "docs" / "cli.md").read_text(encoding="utf-8")
CHANGELOG = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
REPLAN_FLAGS = ["--report", "--dry-run", "--stale", "--limit", "--accept-unplanned"]


def migrating_section() -> str:
    match = re.search(r"^#+ Migrating open changes\n(.*?)(?=^#+ |\Z)", CLI, re.M | re.S)
    assert match, "docs/cli.md has no 'Migrating open changes' section"
    return flat(match.group(1).replace("`", ""))


def unreleased_bullets() -> list[str]:
    unreleased = CHANGELOG.split("\n## ")[1]
    return [flat(b) for b in re.split(r"\n\s*\n", unreleased) if b.lstrip().startswith("- ")]


@pytest.mark.parametrize("flag", REPLAN_FLAGS)
def test_the_migration_section_names_each_replan_flag(flag: str) -> None:
    section = migrating_section()
    assert "abk replan" in section
    assert flag in section


def test_the_migration_section_names_tags_fix_and_the_config_migration() -> None:
    section = migrating_section()
    assert "abk tags --fix" in section
    assert "abk config --migrate" in section


def test_the_migration_section_gives_the_order() -> None:
    section = migrating_section()
    positions = [
        section.index("abk tags --fix"),
        section.index("replan --stale --report"),
        section.index("replan --stale --dry-run"),
        section.index("replan --stale --limit"),
    ]
    assert positions == sorted(positions)


def test_one_unreleased_entry_names_the_migration_commands() -> None:
    wanted = [*REPLAN_FLAGS, "--fix"]
    entries = [b for b in unreleased_bullets() if all(w in b for w in wanted)]
    assert len(entries) == 1
