"""The orientation template and the track prompts do not fix a separation between the planning
repo and the code repos: the planning repo can be a code repo."""

from __future__ import annotations

import re
from pathlib import Path

from agent_build_kit import skills
from tests.prompt_text import flat, placeholders

PACKAGE = Path(skills.SKILLS_DIR).parent
TEMPLATES = PACKAGE / "templates"
ORIENTATIONS = [TEMPLATES / "planning-CLAUDE.md", TEMPLATES / "planning-orientation.md"]
PROMPTS = sorted((PACKAGE / "tracks" / "prompts").rglob("*.md"))

SEPARATION = re.compile(
    r"application code|no (application |source )?code lives here|planning side"
    r"|never (contains?|holds?) (application |source )?code",
    re.I,
)


def test_the_orientation_templates_name_no_fixed_separation() -> None:
    named = [p.name for p in ORIENTATIONS if SEPARATION.search(flat(p.read_text()))]

    assert named == []


def test_the_track_prompts_name_no_fixed_separation() -> None:
    named = [str(p.relative_to(PACKAGE)) for p in PROMPTS if SEPARATION.search(flat(p.read_text()))]

    assert named == []


def test_the_orientation_template_still_formats_with_repo_names() -> None:
    template = (TEMPLATES / "planning-CLAUDE.md").read_text()

    assert placeholders(template) == {"repo_names"}
    filled = flat(template.format(repo_names="app, platform"))
    assert "app, platform" in filled
    assert not SEPARATION.search(filled)


def test_the_in_repo_orientation_says_how_to_work_in_a_working_copy() -> None:
    template = (TEMPLATES / "planning-orientation.md").read_text()

    assert placeholders(template) == {"prefix", "specs_dir", "state_dir", "graph_page"}
    filled = flat(
        template.format(prefix="", specs_dir="openspec", state_dir="runs", graph_page="g.md")
    )
    assert "pipeline worktree" in filled
    assert "--config" in filled
    assert "openspec/changes/" in filled
    assert re.search(r"does not edit the code|not edit the code", filled)
