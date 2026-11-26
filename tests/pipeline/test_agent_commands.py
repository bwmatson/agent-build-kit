"""`red_words_note`: the red words of the profiles a repository uses (spec: tdd-loop)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.config import ProjectConfig
from agent_build_kit.pipeline.agent_commands import red_words_note
from tests.agent_command_fakes import repo_of

PYTHON_ONLY = "NotImplementedError"
NODE_ONLY = "TypeError"


@pytest.mark.parametrize("stubbed", [True, False], ids=["stubbed", "unstubbed"])
def test_a_repo_of_one_profile_gets_its_words_once_with_no_paths(
    tmp_path: Path, stubbed: bool
) -> None:
    alone = red_words_note(repo_of(tmp_path), stubbed=stubbed)
    with_project = red_words_note(
        repo_of(tmp_path, projects=[ProjectConfig(path="web", profile="python-uv")]),
        stubbed=stubbed,
    )

    assert PYTHON_ONLY in alone
    assert with_project == alone
    assert "For " not in alone
    assert "web" not in alone


def test_the_words_depend_on_whether_the_build_is_stubbed(tmp_path: Path) -> None:
    repo = repo_of(tmp_path)

    assert red_words_note(repo, stubbed=True) != red_words_note(repo, stubbed=False)


def test_a_repo_of_two_profiles_gets_one_entry_per_profile_naming_its_paths(
    tmp_path: Path,
) -> None:
    repo = repo_of(tmp_path, projects=[ProjectConfig(path="web", profile="node-npm")])

    entries = red_words_note(repo, stubbed=True).split("\n\n")

    assert len(entries) == 2
    root, web = entries
    assert root.startswith("For .:") and PYTHON_ONLY in root and NODE_ONLY not in root
    assert web.startswith("For web:") and NODE_ONLY in web and PYTHON_ONLY not in web


def test_no_repository_gets_no_words() -> None:
    assert red_words_note(None, stubbed=True) == ""
