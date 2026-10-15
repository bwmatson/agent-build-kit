"""A track run syncs the pipeline worktree before anything else and stops, running no phase, when
it cannot."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.tracks import runner
from tests.factories import commit, git
from tests.planning_worktree_support import InRepo, in_repo, installation_at, publish_elsewhere


class Run:
    """A track run over the pipeline worktree, with what it reaches recorded."""

    def __init__(self, setup: InRepo, patch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        self.setup = setup
        self.worktree_heads: list[str] = []
        self.pulled: list[Path] = []
        self.phases: list[str] = []
        self.project = runner.Project(
            name="platform",
            path=tmp_path / "platform",
            repo="example/platform",
            default_branch="main",
            description="",
            consumes=[],
        )

        self.projects = [self.project]

        def eligible(inst, only=None) -> list[runner.Project]:
            self.look()
            return self.projects

        def pull(path: Path, branch: str) -> bool:
            self.look()
            self.pulled.append(path)
            return True

        def health(inst, project, focus, **kwargs) -> int:
            self.phases.append(project.name)
            return 0

        patch.setattr(runner, "has_headroom", lambda: True)
        patch.setattr(runner, "eligible_projects", eligible)
        patch.setattr(runner, "pull", pull)
        patch.setitem(runner.DISPATCH, "health", health)

    def look(self) -> None:
        self.worktree_heads.append(git(self.setup.worktree, "rev-parse", "HEAD"))

    def run(self, *, dry_run: bool = False) -> int:
        inst = installation_at(self.setup.worktree, self.setup.working_copy)
        return runner.run_track(inst, "health", dry_run=dry_run)


def test_a_track_syncs_the_pipeline_worktree_before_it_pulls_or_picks_a_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup = in_repo(tmp_path)
    tip = publish_elsewhere(setup, {"a.txt": "a\n"})
    run = Run(setup, monkeypatch, tmp_path)

    assert run.run() == 0

    assert run.worktree_heads and set(run.worktree_heads) == {tip}
    assert run.pulled == [run.project.path], "the planning worktree itself is not pulled"
    assert run.phases == ["platform"]


def test_a_stopped_sync_returns_one_and_runs_no_phase(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    setup = in_repo(tmp_path)
    own = commit(setup.worktree, "own.txt")
    publish_elsewhere(setup, {"a.txt": "a\n"})
    run = Run(setup, monkeypatch, tmp_path)

    assert run.run() == 1

    stopped = [line for line in capsys.readouterr().out.splitlines() if "sync stopped" in line]
    assert len(stopped) == 1 and "planning sync stopped: " in stopped[0]
    assert run.phases == [] and run.pulled == []
    assert git(setup.worktree, "rev-parse", "HEAD") == own


def test_a_dry_run_syncs_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    setup = in_repo(tmp_path)
    publish_elsewhere(setup, {"a.txt": "a\n"})
    before = git(setup.worktree, "rev-parse", "HEAD")
    run = Run(setup, monkeypatch, tmp_path)

    assert run.run(dry_run=True) == 0

    assert git(setup.worktree, "rev-parse", "HEAD") == before
    assert run.pulled == []
    assert "planning worktree moved" not in capsys.readouterr().out


def test_the_planning_repos_own_project_is_not_pulled_but_its_phase_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup = in_repo(tmp_path)
    git(setup.working_copy, "checkout", "-q", "-b", "feature")
    (setup.working_copy / "README.md").write_text("edited by a person\n")
    head = git(setup.working_copy, "rev-parse", "HEAD")
    run = Run(setup, monkeypatch, tmp_path)
    app = run.project.model_copy(
        update={"name": "app", "path": setup.working_copy, "repo": "example/app"}
    )
    run.projects = [app, run.project]

    assert run.run() == 0

    assert run.pulled == [run.project.path]
    assert run.phases == ["app", "platform"]
    assert git(setup.working_copy, "symbolic-ref", "--short", "HEAD") == "feature"
    assert git(setup.working_copy, "rev-parse", "HEAD") == head
    assert git(setup.working_copy, "status", "--porcelain") == "M README.md"
