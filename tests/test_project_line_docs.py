"""The documents and the skill describe the `Project:` line (spec: project-lines)."""

from __future__ import annotations

import re
from pathlib import Path

from tests.prompt_text import flat

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "src" / "agent_build_kit" / "skills"


def text(path: Path) -> str:
    return flat(path.read_text(encoding="utf-8").replace("`", ""))


def test_the_authoring_skill_has_a_project_section_beside_manual_and_support() -> None:
    body = (SKILLS / "abk-authoring" / "SKILL.md").read_text(encoding="utf-8")
    headings = re.findall(r"^#+ (.*)$", body, re.M)
    manual = next(i for i, h in enumerate(headings) if "Manual:" in h)
    assert "Project:" in headings[manual + 1], headings


def test_the_authoring_skill_gives_the_three_forms_and_when_each_applies() -> None:
    said = text(SKILLS / "abk-authoring" / "SKILL.md")
    for form in (
        "Project: add <path> <profile>",
        "Project: remove <path>",
        "Project: replace <old> with <new> <profile>",
    ):
        assert form in said, form
    assert re.search(r"Project: add.{0,800}when", said, re.I)
    assert re.search(r"Project: remove.{0,800}(finish|settl|merged)", said, re.I)


def test_the_configuration_document_names_the_line_where_it_describes_projects() -> None:
    body = (ROOT / "docs" / "configuration.md").read_text(encoding="utf-8")
    assert re.search(r"projects.{0,3000}Project:", flat(body.replace("`", "")), re.I)


def test_the_cli_document_describes_the_line_in_tags_and_project_init() -> None:
    said = text(ROOT / "docs" / "cli.md")
    assert re.search(r"abk tags.{0,1200}Project:|Project:.{0,1200}abk tags", said, re.I)
    assert re.search(
        r"abk project init.{0,1200}Project:|Project:.{0,1200}abk project init", said, re.I
    )


def test_the_architecture_and_init_documents_describe_the_round_step_and_the_commit() -> None:
    for name in ("architecture.md", "init.md"):
        said = text(ROOT / "docs" / name)
        assert "Project:" in said, name
        assert re.search(r"Project:.{0,1500}commit|commit.{0,1500}Project:", said, re.I), name


def test_the_init_document_says_a_hand_edit_of_the_file_is_still_possible() -> None:
    said = text(ROOT / "docs" / "init.md")
    assert re.search(r"Project:.{0,2000}by hand|by hand.{0,2000}Project:", said, re.I)
    whole = r"(whole|entire) file"
    assert re.search(rf"Project:.{{0,2000}}{whole}|{whole}.{{0,2000}}Project:", said, re.I)
