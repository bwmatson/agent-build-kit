"""`abk init propose` reads a project's pre-commit configuration and manifest from the project's
folder up to the checkout root, and names each file by its path."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.init.propose import build_prompt
from tests.factories import init_repo
from tests.init.test_propose import detection


def prompt_for(repo: Path) -> str:
    return build_prompt(
        "app",
        detection(repo, projects=[{"path": "libs/svc", "languages": ["python"]}]),
        change="app-code-standards",
        kind="code-standards",
        recommendations="## Linting\n\n- ruff\n",
        repos=("app",),
    )


def test_a_configuration_between_the_root_and_a_project_is_shown_with_its_path(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path / "app")
    (repo / "libs" / "svc").mkdir(parents=True)
    (repo / "libs" / ".pre-commit-config.yaml").write_text("repos: []  # libs hooks\n")

    prompt = prompt_for(repo)

    assert "libs/.pre-commit-config.yaml (first 60 lines)" in prompt
    assert "libs hooks" in prompt


def test_a_manifest_between_the_root_and_a_project_is_shown_with_its_path(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "app")
    (repo / "libs" / "svc").mkdir(parents=True)
    (repo / "libs" / "pyproject.toml").write_text('[project]\nname = "libs-manifest"\n')

    prompt = prompt_for(repo)

    assert "libs/pyproject.toml (first 60 lines)" in prompt
    assert "libs-manifest" in prompt
