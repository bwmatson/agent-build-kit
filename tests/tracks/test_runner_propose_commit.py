"""A track's change is committed to the planning repo's default branch, if it
validates, and is kept out of the pipeline's way if it does not.

The propose phase writes an OpenSpec change that the tick will later plan and
build. It is committed straight to the default branch rather than proposed in a
pull request, so nothing stands between a timer-written spec and the pipeline
except this check: a change that does not validate is worse than no change,
because the tick reads it, cannot plan it, and reports that a cycle later with
nobody present.

Against real git repos and the same agent double as the bookkeeping tests.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.runtimes import AgentInterrupted, AgentRequest
from agent_build_kit.tracks import runner
from tests.factories import git, init_repo
from tests.runtimes.stand_in import StandInRuntime
from tests.tracks.test_runner import make_installation, project


@pytest.fixture
def remote(tmp_path: Path) -> Path:
    path = tmp_path / "origin.git"
    path.mkdir()
    git(path, "init", "-q", "--bare", "-b", "main")
    return path


@pytest.fixture
def inst(tmp_path: Path, remote: Path) -> Installation:
    """A planning repo with real history and a bare `origin` to push to."""
    installation = make_installation(tmp_path / "planning")
    planning = init_repo(installation.root)
    (planning / "README.md").write_text("planning")
    git(planning, "add", "-A")
    git(planning, "commit", "-q", "-m", "start")
    git(planning, "remote", "add", "origin", str(remote))
    git(planning, "push", "-q", "-u", "origin", "main")
    return installation


def count(repo: Path, ref: str = "main") -> int:
    return int(git(repo, "rev-list", "--count", ref))


def branch_of(repo: Path) -> str:
    return git(repo, "symbolic-ref", "--short", "HEAD")


def writes_a_change(inst: Installation, *, valid: bool = True) -> Callable[[AgentRequest], None]:
    """An agent that writes a change and its run log, as the prompt asks."""
    name = runner.proposed_change(project(inst))

    def act(request: AgentRequest) -> None:
        directory = inst.changes_dir / name
        (directory / "specs" / "thing").mkdir(parents=True)
        (directory / "proposal.md").write_text("## Why\n\nA finding.\n")
        (directory / "tasks.md").write_text("## 1. [app] [tier1] Fix it\n\n- [ ] 1.1 Test\n")
        (directory / "specs" / "thing" / "spec.md").write_text("## ADDED Requirements\n")
        log = runner.run_log(inst, project(inst), "propose")
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("# Run log\n\nWrote a change.\n")

    return act


def propose(inst: Installation, runtime: StandInRuntime) -> int:
    return runner.propose(inst, project(inst), runtime=runtime)


@pytest.fixture
def validates(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, tuple[str, ...]]]:
    """`validation_errors` answering "valid", recording what it was asked."""
    asked: list[tuple[str, tuple[str, ...]]] = []

    def fine(planning, change, *, repos, run_openspec=None, specs_dir="openspec"):
        asked.append((change, tuple(repos)))
        return []

    monkeypatch.setattr(runner, "validation_errors", fine)
    return asked


# --- a valid change is committed -----------------------------------------------------


def test_a_valid_change_is_committed_to_the_default_branch_and_pushed(
    inst: Installation, remote: Path, validates: list
) -> None:
    before = count(inst.root)
    name = runner.proposed_change(project(inst))

    assert propose(inst, StandInRuntime(act=writes_a_change(inst))) == 0

    assert count(inst.root) == before + 1, "one commit for the phase, not one per file"
    assert branch_of(inst.root) == "main"
    committed = set(git(inst.root, "show", "--name-only", "--format=", "main").splitlines())
    relative = (inst.changes_dir / name).relative_to(inst.root).as_posix()
    assert {
        f"{relative}/proposal.md",
        f"{relative}/tasks.md",
        f"{relative}/specs/thing/spec.md",
    } <= committed
    assert git(remote, "show", f"main:{relative}/tasks.md"), "and it reached the remote"
    assert git(inst.root, "status", "--porcelain") == ""


def test_the_change_is_validated_against_the_workspace_s_repos(
    inst: Installation, validates: list
) -> None:
    """A group tagged for a repo the workspace does not have is exactly the
    mistake that makes a change unplannable."""
    propose(inst, StandInRuntime(act=writes_a_change(inst)))

    [(asked, repos)] = validates
    assert asked == runner.proposed_change(project(inst))
    assert repos == tuple(inst.repos)


def test_only_the_change_and_the_run_log_are_committed(inst: Installation, validates: list) -> None:
    """The tick's live state sits beside the run log and is not the phase's."""
    live = inst.state_dir / "units.json"

    def act(request: AgentRequest) -> None:
        writes_a_change(inst)(request)
        live.write_text("{}")

    propose(inst, StandInRuntime(act=act))

    committed = git(inst.root, "show", "--name-only", "--format=", "main").splitlines()
    assert live.relative_to(inst.root).as_posix() not in committed
    assert (inst.root / live.relative_to(inst.root)).exists(), "and it is left alone"


# --- an invalid change is not -----------------------------------------------------------


def test_a_change_that_does_not_validate_is_not_committed(
    inst: Installation, remote: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        runner,
        "validation_errors",
        lambda *a, **k: ['tasks.md line 3: unknown repo "elsewhere"'],
    )
    name = runner.proposed_change(project(inst))
    relative = (inst.changes_dir / name).relative_to(inst.root).as_posix()

    propose(inst, StandInRuntime(act=writes_a_change(inst)))

    tree = git(inst.root, "ls-tree", "-r", "--name-only", "main").splitlines()
    assert not any(path.startswith(relative) for path in tree)
    assert not any(
        path.startswith(relative)
        for path in git(remote, "ls-tree", "-r", "--name-only", "main").splitlines()
    )


def test_a_rejected_change_is_taken_out_of_the_tick_s_reach(
    inst: Installation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The tick plans whatever is in `changes/`, committed or not. Leaving an
    invalid change there would have it read, fail to plan, and fail again every
    cycle — so it is moved aside, where a human can still read it."""
    monkeypatch.setattr(runner, "validation_errors", lambda *a, **k: ["tasks.md is missing"])
    name = runner.proposed_change(project(inst))

    propose(inst, StandInRuntime(act=writes_a_change(inst)))

    assert not (inst.changes_dir / name).exists(), "no longer where the tick looks"
    kept = inst.state_dir / "rejected-changes" / name
    assert (kept / "tasks.md").is_file(), "but not thrown away"


def test_a_rejection_leaves_a_note_that_is_committed(
    inst: Installation, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Without one, the tracker says a change is in flight that never was, and
    nothing anywhere says why the run produced nothing."""
    monkeypatch.setattr(runner, "validation_errors", lambda *a, **k: ["tasks.md is missing"])

    propose(inst, StandInRuntime(act=writes_a_change(inst)))

    note = runner.run_log(inst, project(inst), "propose-rejected")
    assert "tasks.md is missing" in note.read_text()
    assert runner.proposed_change(project(inst)) in note.read_text()
    assert (
        note.relative_to(inst.root).as_posix()
        in git(inst.root, "show", "--name-only", "--format=", "main").splitlines()
    )
    assert "tasks.md is missing" in capsys.readouterr().out, "and it is said out loud"


def test_a_run_that_wrote_no_change_commits_only_its_log(
    inst: Installation, validates: list
) -> None:
    """Nothing surviving is a valid outcome, and must not be manufactured into
    one or treated as a failure."""

    def only_a_log(request: AgentRequest) -> None:
        log = runner.run_log(inst, project(inst), "propose")
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("# Run log\n\nNothing actionable.\n")

    assert propose(inst, StandInRuntime(act=only_a_log)) == 0

    assert validates == [], "there was nothing to validate"
    assert git(inst.root, "show", "--name-only", "--format=", "main").splitlines() == [
        runner.run_log(inst, project(inst), "propose").relative_to(inst.root).as_posix()
    ]


def test_a_run_that_was_cut_short_does_not_commit_half_a_change(
    inst: Installation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rate limit partway through leaves whatever was written so far; that
    goes through the same check as a finished one."""
    monkeypatch.setattr(runner, "validation_errors", lambda *a, **k: ["tasks.md is missing"])
    name = runner.proposed_change(project(inst))

    def cut_short(request: AgentRequest) -> None:
        (inst.changes_dir / name).mkdir(parents=True)
        (inst.changes_dir / name / "proposal.md").write_text("## Why\n")
        raise AgentInterrupted("killed")

    propose(inst, StandInRuntime(act=cut_short))

    assert not (inst.changes_dir / name).exists()


# --- what the run is granted ----------------------------------------------------------


def test_a_propose_run_is_granted_its_change_and_nothing_wider(inst: Installation) -> None:
    runtime = StandInRuntime()

    propose(inst, runtime)

    request = runtime.request
    name = runner.proposed_change(project(inst))
    assert request.planning_change_dir == inst.changes_dir / name
    assert request.planning_repo == inst.root
    assert request.planning_state_dir == inst.state_dir


def test_a_discovery_run_is_granted_no_change(inst: Installation) -> None:
    """Health, improve and recommend read; they cannot write what the pipeline
    will build."""
    runtime = StandInRuntime()

    runner.health(inst, project(inst), runtime=runtime)

    assert runtime.request.planning_change_dir is None
