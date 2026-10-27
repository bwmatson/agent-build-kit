"""With the state directory outside the planning repo, the tracks keep their run logs and tracker
under `docs/reports` and commit them by that path (spec: track-reports-dir).

Against real git, as `test_runner_planning_worktree`: the person's working copy, the pipeline
worktree and a bare origin; the state directory is the default one, in the temporary data home."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.runtimes import AgentRequest
from agent_build_kit.tracks import runner
from tests.factories import git
from tests.planning_worktree_support import InRepo, in_repo, installation_at
from tests.runtimes.stand_in import StandInRuntime
from tests.tracks.test_runner import project
from tests.tracks.test_runner_planning_repo import doing, log_name, phase
from tests.tracks.test_runner_propose_commit import writes_a_change

REPORTS = "docs/reports"


def pipeline(tmp_path: Path, data: Path) -> tuple[InRepo, Installation]:
    setup = in_repo(tmp_path)
    git(setup.working_copy, "checkout", "-q", "-b", "feature")
    inst = installation_at(setup.worktree, setup.working_copy)
    assert not inst.state_dir.is_relative_to(inst.root)
    return setup, inst


def origin_main(setup: InRepo) -> str:
    assert setup.origin is not None
    return git(setup.origin, "rev-parse", "main")


def test_the_run_log_is_under_the_reports_directory(tmp_path: Path, data: Path) -> None:
    _, inst = pipeline(tmp_path, data)

    log = runner.run_log(inst, project(inst), "health")

    assert log == inst.root / REPORTS / f"{runner.RUN_ID}-app-health.md"


def test_focus_finds_a_prior_run_log_in_the_reports_directory(tmp_path: Path, data: Path) -> None:
    _, inst = pipeline(tmp_path, data)
    reports = inst.root / REPORTS
    reports.mkdir(parents=True)
    (reports / "20240101-000000-app-health.md").write_text("# earlier\n")

    hint = runner.resolve_focus(inst, project(inst), "health")

    assert "20240101-000000-app-health.md" in hint


def test_a_phase_commits_the_reports_and_not_the_state_and_pushes_them(
    tmp_path: Path, data: Path
) -> None:
    setup, inst = pipeline(tmp_path, data)

    def leaves_markdown_in_the_state() -> None:
        inst.state_dir.mkdir(parents=True, exist_ok=True)
        (inst.state_dir / "notes.md").write_text("live state\n")
        (inst.root / REPORTS).mkdir(parents=True, exist_ok=True)
        (inst.root / REPORTS / "tracked-issues.md").write_text("- an issue\n")

    assert phase(inst, doing(inst, leaves_markdown_in_the_state)) == 0

    committed = git(setup.worktree, "show", "--name-only", "--format=", "HEAD").splitlines()
    assert sorted(committed) == sorted([f"{REPORTS}/tracked-issues.md", log_name(inst)])
    assert log_name(inst).startswith(f"{REPORTS}/")
    assert origin_main(setup) == git(setup.worktree, "rev-parse", "HEAD")
    assert (inst.state_dir / "notes.md").is_file()


def test_a_rejected_change_is_kept_under_the_reports_directory_and_the_note_names_it(
    tmp_path: Path, data: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, inst = pipeline(tmp_path, data)
    monkeypatch.setattr(runner, "validation_errors", lambda *a, **k: ["tasks.md is missing"])
    name = runner.proposed_change(project(inst))

    runner.propose(inst, project(inst), runtime=StandInRuntime(act=writes_a_change(inst)))

    kept = inst.root / REPORTS / "rejected-changes" / name
    assert (kept / "tasks.md").is_file()
    note = runner.run_log(inst, project(inst), "propose-rejected").read_text()
    assert f"{REPORTS}/rejected-changes/{name}" in note


def test_the_working_copy_message_names_the_reports_directory(
    tmp_path: Path, data: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    setup = in_repo(tmp_path)
    inst = installation_at(setup.working_copy, setup.working_copy)

    assert runner.record_planning(inst) is None

    out = capsys.readouterr().out
    assert str(inst.root / REPORTS) in out
    assert str(inst.state_dir) not in out


def test_the_agent_is_granted_the_reports_directory(tmp_path: Path, data: Path) -> None:
    _, inst = pipeline(tmp_path, data)
    runtime = StandInRuntime()

    runner.health(inst, project(inst), runtime=runtime)

    request: AgentRequest = runtime.request
    assert request.planning_reports_dir == inst.root / REPORTS


def test_the_prompt_tokens_for_the_state_directory_are_the_reports_directory(
    tmp_path: Path, data: Path
) -> None:
    _, inst = pipeline(tmp_path, data)

    values = runner.placeholders(inst, project(inst), "health", None)

    assert values["__REPORTS_DIR__"] == str(inst.root / REPORTS)
    assert values["__STATE_DIR__"] == str(inst.root / REPORTS)
