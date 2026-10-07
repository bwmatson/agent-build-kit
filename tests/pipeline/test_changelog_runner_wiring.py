"""The runner `build_runner` assembles passes the repo's `changelog` setting to
the build prompts and to the review, rather than reading a default.

The prompt tests beside this call the convention functions with a repo config in
hand; these go through the runner, where a dropped argument would leave a repo
with the setting off told the convention anyway.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import runtimes
from agent_build_kit.config import RepoConfig
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.stack_runner import UnitRunner
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.wiring import build_runner
from tests.conftest import make_installation
from tests.factories import unit
from tests.graph.test_build_path import build, fresh
from tests.pipeline.test_changelog_prompts import FIXTURE_CONVENTION, packaged, repo_with, squeezed
from tests.runner_fakes import approving
from tests.runtimes.stand_in import StandInRuntime


def runner_for(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, changelog: str | None):
    """The real runner for a unit in `app`, whose setting is `changelog`, and the
    stand-in agent its review asks."""
    root = tmp_path / "planning"
    repos = {
        "app": RepoConfig(path=root / "checkouts" / "app", slug="example/app", changelog=changelog),
    }
    installation: Installation = make_installation(
        root, repos={name: r.model_dump(mode="json") for name, r in repos.items()}
    )
    agent = StandInRuntime(answer=approving())
    monkeypatch.setattr(runtimes, "active", lambda: agent)
    runner = build_runner(
        unit(),
        store=UnitStore(tmp_path / "units.json"),
        installation=installation,
        log=lambda _: None,
    )
    return runner, agent


def worktree(tmp_path: Path, section: str | None) -> Path:
    """The tree the fake build runs in, with an AGENTS.md that has `section`, or none."""
    tree = tmp_path / "tree"
    tree.mkdir()
    return repo_with(tree, section)


def build_prompts_through(runner: UnitRunner, tmp_path: Path) -> list[str]:
    """The tests and implementation prompts a build with this runner's repo setting sends."""
    recorder = fresh(tmp_path)
    build(tmp_path, recorder, repo_config=runner.repo_config)
    return recorder.prompts


def test_the_runner_is_given_the_repo_it_builds_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner, _ = runner_for(tmp_path, monkeypatch, changelog="docs/HISTORY.md")

    assert runner.repo_config is not None
    assert runner.repo_config.changelog == "docs/HISTORY.md"


def test_a_repo_with_the_setting_off_is_told_nothing_of_its_section_when_built_and_reviewed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner, agent = runner_for(tmp_path, monkeypatch, changelog=None)
    tree = worktree(tmp_path, FIXTURE_CONVENTION)

    prompts = build_prompts_through(runner, tmp_path)
    runner.run_review(cwd=tree)

    assert prompts
    for prompt in [*prompts, agent.request.prompt]:
        assert FIXTURE_CONVENTION not in prompt
        assert "changelog" not in prompt.lower()


def test_a_repo_with_the_setting_on_and_no_section_is_told_the_packaged_text_everywhere(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner, agent = runner_for(tmp_path, monkeypatch, changelog="CHANGELOG.md")
    tree = worktree(tmp_path, None)

    prompts = build_prompts_through(runner, tmp_path)
    runner.run_review(cwd=tree)

    assert prompts
    for prompt in [*prompts, agent.request.prompt]:
        assert squeezed(packaged()) in squeezed(prompt)
