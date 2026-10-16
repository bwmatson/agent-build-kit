"""The three shipped skills describe a planning repo that is also a code repo."""

from __future__ import annotations

import re

from agent_build_kit import skills
from tests.prompt_text import flat

NAMES = skills.names()


def body(name: str) -> str:
    return flat((skills.SKILLS_DIR / name / "SKILL.md").read_text())


def version(name: str) -> tuple[int, ...]:
    text = (skills.SKILLS_DIR / name / "SKILL.md").read_text()
    found = re.search(r"^version:\s*([0-9][0-9.]*)\s*$", text, re.M)
    assert found, f"{name} has no version"
    return tuple(int(part) for part in found.group(1).split("."))


def test_every_skill_names_the_pipeline_worktree_and_the_config_to_use() -> None:
    lacking = [n for n in NAMES if "pipeline worktree" not in body(n) or "--config" not in body(n)]

    assert lacking == []


def test_the_config_skill_lists_planning_publish() -> None:
    text = body("abk-config")

    assert "planning.publish" in text
    for mode in ("direct", "branch"):
        assert mode in text


def test_the_pipeline_skill_says_what_a_stopped_sync_means_and_what_to_do() -> None:
    text = body("abk-pipeline")

    for reason in ("diverged", "unfinished", "fetch", "differs"):
        assert re.search(rf"planning sync stopped.{{0,1200}}{reason}", text), reason
    assert re.search(r"planning sync stopped.{0,1200}(to fix|what to do|resolve|reconcile)", text)


def test_every_skills_version_is_raised() -> None:
    assert [n for n in NAMES if version(n) <= (1, 0, 0)] == []
