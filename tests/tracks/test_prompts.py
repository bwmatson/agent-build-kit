"""The shipped prompts are generic and use only the documented placeholders.

The top-level prompts are rendered by the runner, so every `__TOKEN__` in
them must be one it fills. The category playbooks are read from disk by the
subagents the top-level prompts fan out to — never rendered — so they may
not use placeholders at all.

The framework ships to any workspace, so nothing in a prompt may describe
one particular installation. The check is structural rather than a word
list: no home-directory paths, no literal GitHub repos, no `<repo>#<number>`
PR references, no run ids or dates quoting a specific past run.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent_build_kit.tracks import runner

PROMPTS = Path(runner.__file__).parent / "prompts"
TOP_LEVEL = sorted(PROMPTS.glob("*.md"))
CATEGORIES = sorted(PROMPTS.glob("categories/*/*.md"))
SOURCES = sorted(Path(runner.__file__).parent.glob("*.py")) + [
    Path(runner.__file__).parent.parent / "cli" / "tracks.py"
]

PLACEHOLDER = re.compile(r"__[A-Z_]+__")
# Spelled with character classes so this file's own source does not carry
# the shapes it forbids (the repo-wide leak test scans tests too).
INSTALLATION_SPECIFIC = {
    "a home-directory path": re.compile(r"~[/]|[/]home[/]"),
    "a literal GitHub repo": re.compile(r"github\.com[/:][\w.-]+/[\w.-]+"),
    "a repo#N PR reference": re.compile(r"\b[\w-]+#\d+\b"),
    "a run id from a past run": re.compile(r"\b\d{8}-\d{6}\b"),
    "a date": re.compile(r"\b20\d{2}-\d{2}-\d{2}\b"),
}


def test_the_prompt_set_is_complete() -> None:
    assert [p.stem for p in TOP_LEVEL] == sorted(runner.PHASES)
    assert {p.parent.name for p in CATEGORIES} == set(runner.TRACKS)


@pytest.mark.parametrize("path", TOP_LEVEL, ids=lambda p: p.stem)
def test_top_level_prompts_use_only_documented_placeholders(path: Path) -> None:
    used = set(PLACEHOLDER.findall(path.read_text()))

    assert used <= runner.PLACEHOLDERS, used - runner.PLACEHOLDERS
    assert {"__PROJECT__", "__RUN_LOG__", "__STATE_DIR__", "__PLANNING_DIR__"} <= used


@pytest.mark.parametrize("path", TOP_LEVEL, ids=lambda p: p.stem)
def test_each_track_prompt_points_at_its_playbooks(path: Path) -> None:
    text = path.read_text()
    if path.stem in runner.TRACKS:
        assert f"__PROMPTS_DIR__/categories/{path.stem}/" in text
        for playbook in (PROMPTS / "categories" / path.stem).glob("*.md"):
            assert f"`{playbook.stem}`" in text
    else:
        assert "__MAX_ISSUES__" in text and "__FOCUS_HINT__" in text
        assert "__PROPOSED_CHANGE__" in text, "the propose pass names the change it writes"


@pytest.mark.parametrize("path", CATEGORIES, ids=lambda p: f"{p.parent.name}/{p.stem}")
def test_category_playbooks_are_read_raw_so_carry_no_placeholders(path: Path) -> None:
    assert not PLACEHOLDER.findall(path.read_text())


@pytest.mark.parametrize(
    "path", TOP_LEVEL + CATEGORIES + SOURCES, ids=lambda p: f"{p.parent.name}/{p.name}"
)
def test_nothing_describes_one_installation(path: Path) -> None:
    text = path.read_text()
    for what, pattern in INSTALLATION_SPECIFIC.items():
        hits = pattern.findall(text)
        assert not hits, f"{path.name} contains {what}: {hits}"
