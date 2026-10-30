"""The documents and the authoring skill say how a group gets its project
(spec: project-resolution)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = {
    "abk-authoring skill": ROOT
    / "src"
    / "agent_build_kit"
    / "skills"
    / "abk-authoring"
    / "SKILL.md",
    "docs/cli.md": ROOT / "docs" / "cli.md",
    "docs/designs/unit-graph.md": ROOT / "docs" / "designs" / "unit-graph.md",
    "docs/runbooks/landing-changes.md": ROOT / "docs" / "runbooks" / "landing-changes.md",
}


def squashed(path: Path) -> str:
    """The file's text on one line with the code ticks dropped, so a wrapped sentence matches."""
    return " ".join(path.read_text(encoding="utf-8").replace("`", "").split())


@pytest.mark.parametrize("name", DOCUMENTS)
def test_each_document_says_a_group_resolves_to_a_project_or_stays_in_the_root(name: str) -> None:
    text = squashed(DOCUMENTS[name])
    assert re.search(r"resolv", text, re.I), f"{name} does not say a group resolves its project"
    assert "Paths:" in text, f"{name} lacks the Paths: line"
    assert re.search(r"outside (a|any|every) (declared )?project.{0,200}root", text, re.I), (
        f"{name} lacks that a path outside a project stays in the root"
    )
    assert "<root>" in text, f"{name} lacks the [repo/<root>] opt-out"


@pytest.mark.parametrize("name", ["abk-authoring skill", "docs/designs/unit-graph.md"])
def test_the_skill_and_the_graph_document_say_what_paths_and_reads_lines_are(name: str) -> None:
    text = squashed(DOCUMENTS[name])
    assert re.search(r"Paths:.{0,200}(authoritative|decides?|names?)", text), name
    assert re.search(r"Reads:.{0,200}(not (a )?change|does not|ignored|read)", text), name


def test_the_cli_document_and_the_skill_describe_fix_projects() -> None:
    for name in ("docs/cli.md", "abk-authoring skill"):
        text = squashed(DOCUMENTS[name])
        assert "--fix-projects" in text, name
        assert re.search(r"--fix-projects.{0,300}(heading|repo)", text), name


def test_the_runbook_says_to_name_the_project_or_add_a_paths_line_or_let_it_resolve() -> None:
    text = squashed(DOCUMENTS["docs/runbooks/landing-changes.md"])
    assert re.search(r"name the project", text, re.I)
    assert re.search(r"add a Paths: line", text, re.I)
    assert re.search(r"let it resolve", text, re.I)


def test_the_changelog_has_one_bullet_for_the_resolution() -> None:
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    unreleased = changelog.split("\n## ", 2)[1]
    assert len(re.findall(r"--fix-projects", unreleased)) == 1
