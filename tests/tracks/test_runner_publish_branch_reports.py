"""Under `planning.publish: branch` with the state directory outside the planning repo, the
`planning/...` branch holds only files under `docs/reports`, and what an earlier phase left dirty
there is kept (spec: track-reports-dir)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_build_kit import forges
from agent_build_kit.installation import Installation
from agent_build_kit.runtimes import AgentRequest
from agent_build_kit.tracks import runner
from tests.factories import git
from tests.planning_worktree_support import InRepo, in_repo, installation_at
from tests.runtimes.stand_in import StandInRuntime
from tests.tracks.test_runner import project
from tests.tracks.test_runner_planning_repo import doing, log_name, phase, write_run_log
from tests.tracks.test_runner_publish_branch import Host, origin_of

REPORTS = "docs/reports"


@pytest.fixture(autouse=True)
def code_host() -> Iterator[Host]:
    stand_in = Host(number=41)
    forges.register(stand_in)
    yield stand_in  # the suite's autouse fixture puts the real forge back


def pipeline(tmp_path: Path) -> tuple[InRepo, Installation]:
    setup = in_repo(tmp_path)
    git(setup.working_copy, "checkout", "-q", "-b", "feature")
    inst = installation_at(setup.worktree, setup.working_copy, planning=dict(publish="branch"))
    assert not inst.state_dir.is_relative_to(inst.root)
    return setup, inst


def test_the_planning_branch_holds_only_files_under_the_reports_directory(
    tmp_path: Path, data: Path
) -> None:
    setup, inst = pipeline(tmp_path)
    branch = f"planning/{runner.RUN_ID}-app-health"

    def leaves_markdown_in_the_state() -> None:
        inst.state_dir.mkdir(parents=True, exist_ok=True)
        (inst.state_dir / "notes.md").write_text("live state\n")

    assert phase(inst, doing(inst, leaves_markdown_in_the_state)) == 0

    published = git(origin_of(setup), "show", "--name-only", "--format=", branch).splitlines()
    assert published == [log_name(inst)]
    assert log_name(inst).startswith(f"{REPORTS}/")


def test_a_file_an_earlier_phase_left_dirty_is_kept_and_not_published_again(
    tmp_path: Path, data: Path
) -> None:
    setup, inst = pipeline(tmp_path)

    def write(request: AgentRequest) -> None:
        write_run_log(inst, "improve")

    assert phase(inst, doing(inst)) == 0
    improve = StandInRuntime(act=write)
    assert runner.claude_phase(inst, project=project(inst), name="improve", runtime=improve) == 0

    second = f"planning/{runner.RUN_ID}-app-improve"
    published = runner.run_log(inst, project(inst), "improve").relative_to(inst.root).as_posix()
    assert git(origin_of(setup), "show", "--name-only", "--format=", second).splitlines() == [
        published
    ]
    assert (setup.worktree / log_name(inst)).is_file(), "the earlier log is kept in the worktree"
