"""The documents, the skill and the changelog say the migration moves machine settings."""

from __future__ import annotations

import re

from tests.doc_text import ROOT, squashed, unreleased_bullets

CLI = ROOT / "docs" / "cli.md"
CONFIGURATION = ROOT / "docs" / "configuration.md"
SKILL = ROOT / "src" / "agent_build_kit" / "skills" / "abk-config" / "SKILL.md"


def section(text: str, heading: str, level: str) -> str:
    start = text.index(heading)
    nxt = re.search(rf"^{level} ", text[start + len(heading) :], re.M)
    end = start + len(heading) + nxt.start() if nxt else len(text)
    return squashed(text[start:end])


def test_the_configuration_document_says_migrate_moves_the_machine_settings() -> None:
    text = CONFIGURATION.read_text(encoding="utf-8")
    start = text.index("`abk.yaml` should read the same on every machine")
    paragraph = squashed(text[start : text.index("\n## ", start)])
    assert re.search(r"abk config --migrate.{0,120}moves.{0,120}abk\.local\.yaml", paragraph)
    assert re.search(r"tracked.{0,40}abk\.yaml|abk\.yaml.{0,40}tracked", paragraph)
    assert "--include-defaults" in paragraph
    assert re.search(
        r"default.{0,200}--include-defaults|--include-defaults.{0,200}default", paragraph
    )


def test_the_configuration_document_lists_the_move_near_the_second_table() -> None:
    text = CONFIGURATION.read_text(encoding="utf-8")
    block = section(text, "#### Which file holds a setting", "#{1,4}")
    assert "abk config --migrate" in block
    assert "--include-defaults" in block


def test_the_cli_synopsis_has_include_defaults() -> None:
    text = CLI.read_text(encoding="utf-8")
    heading = next(ln for ln in text.splitlines() if ln.startswith("### `abk config "))
    assert "[--include-defaults]" in heading


def test_the_cli_section_says_what_the_machine_move_writes_and_leaves() -> None:
    text = CLI.read_text(encoding="utf-8")
    body = section(text, "### `abk config ", "###")
    assert re.search(r"abk\.yaml and abk\.local\.yaml.{0,80}together", body)
    assert re.search(r"one backup of each|a backup of each", body)
    assert re.search(r"(local file|abk\.local\.yaml) (already )?sets.{0,120}report", body)
    assert re.search(r"\.gitignore|ignore lines", body)
    assert re.search(r"never commits", body)
    assert re.search(r"running units?", body)
    assert "--include-defaults" in body


def test_the_skill_names_the_command_in_which_file_holds_what() -> None:
    text = SKILL.read_text(encoding="utf-8")
    body = section(text, "## Which file holds what", "##")
    assert "abk config --migrate" in body
    assert "--include-defaults" in body


def test_the_changelog_holds_one_bullet_for_the_machine_move() -> None:
    bullets = [b for b in unreleased_bullets() if "--include-defaults" in b]
    assert len(bullets) == 1
    assert re.search(r"running units?", bullets[0])
    assert "never commits" in bullets[0] or "does not commit" in bullets[0]
