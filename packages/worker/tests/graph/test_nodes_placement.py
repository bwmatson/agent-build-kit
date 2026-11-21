"""The build's tests step tells the agent where a new test goes, by the profiles the repo uses
(spec: red-check-by-id).

The agent is faked at the recorder's edge, which keeps each prompt it was handed."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.config import ProjectConfig, RepoConfig
from agent_build_kit.pipeline.agent_commands import placement_note
from tests.agent_command_fakes import repo_of
from tests.graph_driver import fresh, tick
from tests.prompt_text import flat

IN_EXISTING_FILE = "existing test file for the module it exercises"
IN_ALL_FAILING_FILES = "test files in which every test fails before the implementation"
NODE_WEB = ProjectConfig(path="web", profile="node-npm")


def prompt_sent(where: Path, repo: RepoConfig) -> str:
    """What the tests step hands the agent for a unit of `repo`."""
    recorder = fresh(where)
    tick(where, recorder, repo_config=repo)
    return flat(recorder.prompts[0])


def test_a_python_repo_is_told_to_add_a_case_to_the_existing_file(tmp_path: Path) -> None:
    text = prompt_sent(tmp_path, repo_of(tmp_path))

    assert IN_EXISTING_FILE in text
    assert IN_ALL_FAILING_FILES not in text


def test_a_node_repo_is_told_to_keep_new_tests_in_all_failing_files(tmp_path: Path) -> None:
    text = prompt_sent(tmp_path, repo_of(tmp_path, profile="node-npm"))

    assert IN_ALL_FAILING_FILES in text
    assert "existing test file" not in text


def test_a_python_repo_with_a_node_project_is_told_the_whole_file_rule(tmp_path: Path) -> None:
    repo = repo_of(tmp_path, projects=[ProjectConfig(path="."), NODE_WEB])

    text = prompt_sent(tmp_path, repo)

    assert IN_ALL_FAILING_FILES in text
    assert "existing test file" not in text


def test_a_node_repo_with_a_python_project_is_told_the_whole_file_rule() -> None:
    repo = RepoConfig(
        path=Path("."),
        slug="example/app",
        profile="node-npm",
        projects=[ProjectConfig(path="svc", profile="python-uv")],
    )

    assert placement_note(repo) == ""


def test_projects_that_share_one_placement_use_it() -> None:
    repo = RepoConfig(
        path=Path("."),
        slug="example/app",
        projects=[ProjectConfig(path="a"), ProjectConfig(path="b")],
    )

    assert IN_EXISTING_FILE in flat(placement_note(repo))
