"""Under `planning.publish: branch` a phase's bookkeeping goes to a `planning/...` branch and a pull
request, and the pipeline worktree stays at the head it had so the next sync fast-forwards.

Against real git (a bare origin and the pipeline worktree) and a stand-in code host registered under
the name the repos default to, so the pull request it is asked to open is recorded."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_build_kit import forges
from agent_build_kit.installation import Installation
from agent_build_kit.tracks import runner
from tests.factories import commit_files, git, init_repo
from tests.forges.stand_in import StandInForge
from tests.planning_worktree_support import InRepo, in_repo, installation_at
from tests.tracks.test_runner_planning_repo import doing, log_name, phase


class Host(StandInForge):
    """The stand-in, answering to the name a repo's `forge` defaults to."""

    name = "github"


@pytest.fixture
def host() -> Iterator[Host]:
    stand_in = Host(number=41)
    forges.register(stand_in)
    yield stand_in  # the suite's autouse fixture puts the real forge back


def pipeline(tmp_path: Path, publish: str) -> tuple[InRepo, Installation]:
    setup = in_repo(tmp_path)
    git(setup.working_copy, "checkout", "-q", "-b", "feature")
    inst = installation_at(setup.worktree, setup.working_copy, planning=dict(publish=publish))
    return setup, inst


def origin_of(setup: InRepo) -> Path:
    assert setup.origin is not None
    return setup.origin


def origin_ref(setup: InRepo, ref: str) -> str:
    return git(origin_of(setup), "rev-parse", "--verify", "-q", ref)


def test_a_phase_s_commit_is_published_on_a_planning_branch_with_a_pull_request(
    tmp_path: Path, host: Host
) -> None:
    setup, inst = pipeline(tmp_path, "branch")
    recorded = git(setup.worktree, "rev-parse", "HEAD")
    branch = f"planning/{runner.RUN_ID}-app-health"

    assert phase(inst, doing(inst)) == 0

    assert git(origin_of(setup), "show", "--name-only", "--format=", branch).splitlines() == [
        log_name(inst)
    ]
    assert [(c["head"], c["base"]) for c in host.created] == [(branch, "main")]
    assert origin_ref(setup, "main") == recorded
    assert git(setup.worktree, "rev-parse", "HEAD") == recorded
    assert (setup.worktree / log_name(inst)).read_text().startswith("# Run log")


def test_under_direct_nothing_is_opened_and_the_default_branch_moves(
    tmp_path: Path, host: Host
) -> None:
    setup, inst = pipeline(tmp_path, "direct")

    assert phase(inst, doing(inst)) == 0

    assert host.created == []
    assert origin_ref(setup, "main") == git(setup.worktree, "rev-parse", "HEAD")
    assert git(origin_of(setup), "branch", "--list", "planning/*") == ""


def test_the_setting_has_no_effect_in_a_separate_root(tmp_path: Path, host: Host) -> None:
    remote = tmp_path / "origin.git"
    remote.mkdir()
    git(remote, "init", "-q", "--bare", "-b", "main")
    planning = init_repo(tmp_path / "planning")
    commit_files(planning, "start", {"one.md": "one\n"})
    git(planning, "remote", "add", "origin", str(remote))
    git(planning, "push", "-q", "-u", "origin", "main")
    inst = installation_at(planning, planning, planning=dict(publish="branch"))
    before = git(remote, "rev-parse", "main")

    assert phase(inst, doing(inst)) == 0

    assert host.created == []
    assert git(remote, "rev-parse", "main") != before
    assert git(remote, "branch", "--list", "planning/*") == ""
