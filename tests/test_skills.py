"""The shipped skills, templates and recommendation seeds: well-formed, and
free of anything that names a particular installation.

This is a public framework. A skill that mentions one user's repo, home
directory or PR would be wrong in every other installation, so the rule is
mechanical: nothing under skills/, templates/ or recommendations/ contains a
home path, a tilde-relative path or an owner/name#N-style PR reference.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from agent_build_kit import __version__, skills

PACKAGE = Path(skills.SKILLS_DIR).parent
SHIPPED = sorted(
    [
        *PACKAGE.glob("skills/*/SKILL.md"),
        *PACKAGE.glob("templates/**/*"),
        *PACKAGE.glob("recommendations/*.md"),
    ]
)
SHIPPED = [path for path in SHIPPED if path.is_file()]

LEAKS = {
    "home path": re.compile(r"/home/"),
    "tilde path": re.compile("~" + "/"),
    "PR reference": re.compile(r"\b[\w.-]+/[\w.-]+#\d+"),
}


def frontmatter(path: Path) -> dict:
    text = path.read_text()
    assert text.startswith("---\n"), f"{path} has no frontmatter"
    _, block, _body = text.split("---\n", 2)
    loaded = yaml.safe_load(block)
    assert isinstance(loaded, dict)
    return loaded


def test_three_skills_ship() -> None:
    assert skills.names() == ["abk-authoring", "abk-config", "abk-pipeline"]


@pytest.mark.parametrize("name", skills.names())
def test_skill_frontmatter(name: str) -> None:
    meta = frontmatter(skills.SKILLS_DIR / name / "SKILL.md")

    assert meta["name"] == name
    assert meta["description"].startswith("TRIGGER — ")
    assert " SKIP " in meta["description"]
    assert meta["version"] == "1.0.0"
    assert meta["generatedBy"] == "agent-build-kit"


@pytest.mark.parametrize("name", skills.names())
def test_rendered_skill_carries_the_framework_version(name: str) -> None:
    rendered = skills.rendered(name)

    assert f"generatedBy: agent-build-kit {__version__}" in rendered
    assert yaml.safe_load(rendered.split("---\n", 2)[1])["name"] == name


@pytest.mark.parametrize("path", SHIPPED, ids=lambda p: str(p.relative_to(PACKAGE)))
def test_shipped_text_names_no_installation(path: Path) -> None:
    text = path.read_text()
    for what, pattern in LEAKS.items():
        found = pattern.findall(text)
        assert not found, f"{path.relative_to(PACKAGE)} has a {what}: {found}"


def test_stale_detection(tmp_path: Path) -> None:
    written, refused = skills.install(tmp_path)
    assert len(written) == 3 and not refused
    assert skills.stale(tmp_path) == []

    old = tmp_path / "abk-pipeline" / "SKILL.md"
    old.write_text(
        old.read_text().replace(f"agent-build-kit {__version__}", "agent-build-kit 0.0.1")
    )
    assert [s.name for s in skills.stale(tmp_path)] == ["abk-pipeline"]

    (tmp_path / "abk-config" / "SKILL.md").write_text("---\nname: abk-config\n---\n")
    assert [s.name for s in skills.stale(tmp_path)] == ["abk-pipeline"], "not ours: not stale"
    _written, refused = skills.install(tmp_path)
    assert [p.parent.name for p in refused] == ["abk-config"]
