"""Each shipped skill says a person merges what was not auto-landed and the build agent never
merges, states no older rule, and is written unchanged to the mirror in `.claude/skills`."""

from pathlib import Path

import pytest

from agent_build_kit import skills
from tests.old_merge_rule import statements
from tests.prompt_text import flat

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("name", skills.names())
def test_the_skill_says_who_merges_and_equals_its_mirror(name: str, tmp_path: Path) -> None:
    text = flat(skills.source(name))
    assert statements(skills.source(name)) == [], name
    assert "build agent never merges" in text, name
    assert "auto-landed" in text, name

    mirror = tmp_path / ".claude" / "skills"
    skills.install(mirror)
    assert (mirror / name / "SKILL.md").read_text(encoding="utf-8") == skills.rendered(name), name

    repo_mirror = ROOT / ".claude" / "skills" / name / "SKILL.md"
    if repo_mirror.is_file():
        assert repo_mirror.read_text(encoding="utf-8") == skills.rendered(name), name
