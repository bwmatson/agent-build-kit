"""The archive commits its result and publishes it as `planning.publish` says.

Driven through `abk verify <change>` over real git (a bare origin and the pipeline worktree), the
real archive step and a stand-in for the OpenSpec CLI that does what the CLI does to the files:
moves the change into `archive/` and writes the synced main spec."""

from __future__ import annotations

import argparse
import shutil
import stat
from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_build_kit import forges, openspec
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.planning_sync import SyncOutcome, sync_planning
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.verify import Verification
from agent_build_kit.tracks import runner
from tests.factories import commit_files, git, init_repo, stored_unit
from tests.forges.stand_in import StandInForge
from tests.planning_worktree_support import (
    InRepo,
    in_repo,
    installation_at,
    publish_elsewhere,
)
from tests.progress_support import copy_file, write_copy
from tests.tracks.test_runner_publish_branch import Host

CHANGE = "feature"
ARCHIVED = f"openspec/changes/archive/2026-01-01-{CHANGE}"
UNTICKED = "## 1. [app] [unit-test] Alpha\n- [ ] 1.1 Test: a\n- [ ] 1.2 Do a\n"
TICKED = UNTICKED.replace("[ ]", "[x]")
FOLLOW_UPS = "## From `feature/1`\n\n- tidy the helper\n"
FILES = {
    f"openspec/changes/{CHANGE}/proposal.md": "# Proposal\n",
    f"openspec/changes/{CHANGE}/tasks.md": UNTICKED,
    "openspec/specs/marker/spec.md": "old spec\n",
    "abk.yaml": "repos: {}\n",
    "src/main.py": "print('main')\n",
}
ARCHIVE_COMMIT = {
    f"{ARCHIVED}/proposal.md",
    f"{ARCHIVED}/tasks.md",
    f"{ARCHIVED}/follow-ups.md",
    f"openspec/changes/{CHANGE}/proposal.md",
    f"openspec/changes/{CHANGE}/tasks.md",
    "openspec/specs/marker/spec.md",
}


def fake_archive(change: str, *, cwd: Path, run=None) -> str:
    """What `openspec archive` does to the files."""
    changes = cwd / "openspec" / "changes"
    (changes / "archive").mkdir(exist_ok=True)
    shutil.move(changes / change, changes / "archive" / f"2026-01-01-{change}")
    (cwd / "openspec" / "specs" / "marker" / "spec.md").write_text("synced spec\n")
    return "archived"


@pytest.fixture(autouse=True)
def openspec_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(openspec, "archive", fake_archive)


@pytest.fixture
def host() -> Iterator[StandInForge]:
    stand_in = Host(number=41)
    forges.register(stand_in)
    yield stand_in


def origin_of(setup: InRepo) -> Path:
    assert setup.origin is not None
    return setup.origin


def pipeline(tmp_path: Path, publish: str = "direct") -> tuple[InRepo, Installation]:
    setup = in_repo(tmp_path, files=FILES)
    inst = installation_at(
        setup.worktree,
        setup.working_copy,
        planning=dict(publish=publish, state_dir=str(tmp_path / "state")),
    )
    return setup, inst


def merged_change(inst: Installation) -> None:
    """A merged change with a ticked copy and a follow-up, and dirt the archive must not commit."""
    write_copy(inst, CHANGE, TICKED)
    copy_file(inst, CHANGE, "follow-ups.md").write_text(FOLLOW_UPS)
    UnitStore(inst.state_dir / "units.json").upsert([stored_unit(f"{CHANGE}/1", state="merged")])
    (inst.root / "abk.yaml").write_text("repos: {changed: true}\n")
    (inst.root / "src" / "main.py").write_text("print('dirty')\n")


def verify(inst: Installation, monkeypatch: pytest.MonkeyPatch) -> int:
    def passed(inst: Installation, change: str, units: list) -> Verification:
        return Verification(change=change, passed=True)

    monkeypatch.setattr(cli, "verify_one", passed)
    return cli.cmd_verify(argparse.Namespace(change=CHANGE), inst)


def committed_paths(repo: Path, ref: str) -> set[str]:
    return set(git(repo, "show", "--no-renames", "--name-only", "--format=", ref).splitlines())


def test_one_commit_reaches_the_default_branch_with_the_archive_and_nothing_else(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup, inst = pipeline(tmp_path)
    merged_change(inst)
    before = git(origin_of(setup), "rev-parse", "main")

    assert verify(inst, monkeypatch) == 0

    origin = origin_of(setup)
    assert git(origin, "rev-list", "--count", f"{before}..main") == "1"
    assert git(origin, "log", "-1", "--format=%s", "main") == f"archive: {CHANGE}"
    assert committed_paths(origin, "main") == ARCHIVE_COMMIT
    assert git(origin, "show", f"main:{ARCHIVED}/tasks.md") == TICKED.strip()
    assert git(origin, "show", f"main:{ARCHIVED}/follow-ups.md") == FOLLOW_UPS.strip()
    assert git(origin, "show", "main:openspec/specs/marker/spec.md") == "synced spec"
    dirty = git(setup.worktree, "status", "--porcelain").splitlines()
    assert {line.split()[-1] for line in dirty} == {"abk.yaml", "src/main.py"}
    assert not copy_file(inst, CHANGE).exists()


def test_a_commit_pushed_first_is_rebased_over(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup, inst = pipeline(tmp_path)
    merged_change(inst)
    theirs = publish_elsewhere(setup, {"notes.md": "a person's note\n"})

    assert verify(inst, monkeypatch) == 0

    origin = origin_of(setup)
    assert git(origin, "rev-parse", "main~1") == theirs
    assert committed_paths(origin, "main") == ARCHIVE_COMMIT
    assert git(setup.worktree, "rev-parse", "HEAD") == git(origin, "rev-parse", "main")


def test_branch_publication_opens_a_pull_request_and_leaves_the_worktree_to_fast_forward(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, host: StandInForge
) -> None:
    setup, inst = pipeline(tmp_path, publish="branch")
    merged_change(inst)
    earlier = git(setup.worktree, "rev-parse", "HEAD")
    head = f"planning/archive-{CHANGE}-{runner.RUN_ID}"

    assert verify(inst, monkeypatch) == 0

    origin = origin_of(setup)
    assert git(origin, "rev-parse", "main") == earlier
    assert committed_paths(origin, head) == ARCHIVE_COMMIT
    assert [(c["head"], c["base"]) for c in host.created] == [(head, "main")]
    assert CHANGE in host.created[0]["title"]
    assert git(setup.worktree, "rev-parse", "HEAD") == earlier
    assert (setup.worktree / ARCHIVED / "tasks.md").read_text() == TICKED

    git(origin, "update-ref", "refs/heads/main", f"refs/heads/{head}")
    synced = sync_planning(inst, lambda message: None)

    assert synced.outcome == SyncOutcome.SYNCED, synced.reason
    assert git(setup.worktree, "rev-parse", "HEAD") == git(origin, "rev-parse", "main")


def test_a_rejected_second_push_keeps_the_commit_and_does_not_fail_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup, inst = pipeline(tmp_path)
    merged_change(inst)
    origin = origin_of(setup)
    before = git(origin, "rev-parse", "main")
    attempts = origin / "attempts"
    hook = origin / "hooks" / "pre-receive"
    hook.write_text(f"#!/bin/sh\necho x >> {attempts}\necho 'remote says no' >&2\nexit 1\n")
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR)

    assert verify(inst, monkeypatch) == 0

    assert len(attempts.read_text().splitlines()) == 2, "one push, and one retry"
    assert git(origin, "rev-parse", "main") == before
    assert git(setup.worktree, "log", "-1", "--format=%s") == f"archive: {CHANGE}"


def test_a_separate_installation_pushes_its_current_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    origin = tmp_path / "origin.git"
    origin.mkdir()
    git(origin, "init", "-q", "--bare", "-b", "main")
    planning = init_repo(tmp_path / "planning")
    commit_files(planning, "start", FILES)
    git(planning, "remote", "add", "origin", str(origin))
    git(planning, "checkout", "-q", "-b", "trunk")
    git(planning, "push", "-q", "-u", "origin", "trunk")
    inst = installation_at(
        planning, init_repo(tmp_path / "code"), planning=dict(state_dir=str(tmp_path / "state"))
    )
    merged_change(inst)

    assert verify(inst, monkeypatch) == 0

    assert committed_paths(origin, "trunk") == ARCHIVE_COMMIT
    assert git(origin, "branch", "--list", "main") == ""
