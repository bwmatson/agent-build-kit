"""`publish_commit` pushes the commit at HEAD of a pipeline worktree, as the tracks' bookkeeping
commit does and as the archive now does too.

Against real git (a bare origin and the pipeline worktree) and a stand-in code host."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_build_kit import forges
from agent_build_kit.installation import Installation
from agent_build_kit.tracks.runner import publish_commit
from tests.factories import commit_files, git
from tests.forges.stand_in import StandInForge
from tests.planning_worktree_support import (
    InRepo,
    in_repo,
    installation_at,
    publish_elsewhere,
)
from tests.tracks.test_runner_publish_branch import Host

LABEL = "archive-feature-20260101-000000"
MESSAGE = "archive: feature"
BODY = "abk archived the change `feature`."


@pytest.fixture
def host() -> Iterator[StandInForge]:
    stand_in = Host(number=41)
    forges.register(stand_in)
    yield stand_in


def committed(
    tmp_path: Path, publish: str = "direct", files: dict[str, str] | None = None
) -> tuple[InRepo, Installation, str]:
    """A pipeline worktree with one commit made on top of its tip; the commit before it."""
    setup = in_repo(tmp_path)
    inst = installation_at(
        setup.worktree, setup.working_copy, planning=dict(publish=publish, state_dir="runs")
    )
    earlier = git(setup.worktree, "rev-parse", "HEAD")
    commit_files(setup.worktree, MESSAGE, files or {"archived.md": "archived\n"})
    return setup, inst, earlier


def origin_ref(setup: InRepo, ref: str) -> str:
    assert setup.origin is not None
    return git(setup.origin, "rev-parse", "--verify", "-q", ref)


def test_a_direct_publish_pushes_head_to_the_default_branch(tmp_path: Path) -> None:
    setup, inst, earlier = committed(tmp_path)

    publish_commit(inst, "main", LABEL, MESSAGE, earlier, BODY)

    assert origin_ref(setup, "main") == git(setup.worktree, "rev-parse", "HEAD")


def test_a_moved_remote_is_fetched_rebased_over_and_pushed_once_more(tmp_path: Path) -> None:
    setup, inst, earlier = committed(tmp_path)
    theirs = publish_elsewhere(setup, {"theirs.md": "theirs\n"})

    publish_commit(inst, "main", LABEL, MESSAGE, earlier, BODY)

    tip = origin_ref(setup, "main")
    assert tip == git(setup.worktree, "rev-parse", "HEAD")
    assert git(setup.worktree, "log", "-1", "--format=%s") == MESSAGE
    assert git(setup.worktree, "rev-parse", "HEAD~1") == theirs
    assert git(setup.worktree, "show", f"{tip}:archived.md") == "archived"


def test_a_conflict_aborts_the_rebase_keeps_the_commit_and_logs_once_with_the_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    setup, inst, earlier = committed(tmp_path, files={"README.md": "ours\n"})
    ours = git(setup.worktree, "rev-parse", "HEAD")
    theirs = publish_elsewhere(setup, {"README.md": "theirs\n"})

    publish_commit(inst, "main", LABEL, MESSAGE, earlier, BODY)

    assert origin_ref(setup, "main") == theirs
    assert git(setup.worktree, "rev-parse", "HEAD") == ours, "the commit is kept, not mid-rebase"
    assert git(setup.worktree, "status", "--porcelain") == ""
    rejected = [line for line in capsys.readouterr().out.splitlines() if "rejected" in line]
    assert len(rejected) == 1
    assert str(inst.root) in rejected[0]


def test_a_branch_publish_pushes_a_planning_branch_resets_head_and_opens_a_pull_request(
    tmp_path: Path, host: StandInForge
) -> None:
    setup, inst, earlier = committed(tmp_path, publish="branch")
    commit = git(setup.worktree, "rev-parse", "HEAD")

    publish_commit(inst, "main", LABEL, MESSAGE, earlier, BODY)

    assert origin_ref(setup, f"planning/{LABEL}") == commit
    assert origin_ref(setup, "main") == earlier
    assert git(setup.worktree, "rev-parse", "HEAD") == earlier
    assert (setup.worktree / "archived.md").read_text() == "archived\n"
    assert host.created == [
        {"head": f"planning/{LABEL}", "base": "main", "title": MESSAGE, "body": BODY}
    ]
