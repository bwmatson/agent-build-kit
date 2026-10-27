"""The documents, the skill, the changelog and the pull request wording describe where progress is
tracked, where the change locks are, and what the archive writes and commits."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.docs.test_fixers_documented import squashed, squashed_text, unreleased_section

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "src" / "agent_build_kit"
ARCHITECTURE = ROOT / "docs" / "architecture.md"
SKILL = PACKAGE / "skills" / "abk-pipeline" / "SKILL.md"
PR_BODY = PACKAGE / "pipeline" / "pr_body.py"
COPY = "<state dir>/changes/<change>/"


def texts() -> dict[str, str]:
    return {
        "docs/architecture.md": squashed(ARCHITECTURE),
        "the abk-pipeline skill": squashed(SKILL),
        "the changelog's Unreleased section": squashed_text(unreleased_section()),
    }


@pytest.mark.parametrize("name", list(texts()))
def test_ticks_and_follow_ups_are_said_to_live_in_the_state_directory(name: str) -> None:
    assert COPY in texts()[name]


@pytest.mark.parametrize("name", list(texts()))
def test_the_change_locks_are_said_to_be_under_the_local_directory(name: str) -> None:
    assert re.search(r"locks?[^.]*local (dir|directory)", texts()[name], re.I), name


@pytest.mark.parametrize("name", list(texts()))
def test_the_archive_is_said_to_write_the_final_files_and_commit_them(name: str) -> None:
    text = texts()[name]
    assert re.search(r"archive[^.]*final files", text, re.I), name
    assert re.search(r"archive[^.]*\bcommit", text, re.I), name


@pytest.mark.parametrize("name", list(texts()))
def test_what_a_person_loses_is_said(name: str) -> None:
    assert re.search(r"until (the change is |it is |the archive)?\s*archiv", texts()[name], re.I), (
        name
    )


def test_the_state_on_disk_table_lists_the_changes_folder_and_the_lock_directory() -> None:
    text = ARCHITECTURE.read_text(encoding="utf-8")
    section = squashed_text(text[text.index("## State on disk") :].split("\n## ", 1)[0])
    assert COPY in section
    assert "locks/changes/" in section


def test_the_pull_request_body_says_tasks_are_recorded_as_done() -> None:
    text = squashed(PR_BODY)
    assert "recorded as done" in text
    assert "ticked in tasks.md all the same" not in text
