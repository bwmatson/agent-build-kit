"""The build and review runs reach their agent through the runtime seam.

Given a runtime that is not Claude Code, each run is asked for in abk's own
terms — a worktree, the specs it may read, a tool policy, a model already
resolved for its role — and nothing it sends can be a `claude` flag.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent_build_kit import runtimes
from agent_build_kit.config import RepoConfig, models
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.wiring import (
    REVIEW_PROMPT,
    REVIEW_TOOLS,
    AgentPushed,
    build_run,
    build_run_review,
    build_runner,
)
from agent_build_kit.runtimes import ToolPolicy
from tests.conftest import make_installation
from tests.factories import git, init_repo, unit
from tests.runtimes.stand_in import StandInRuntime

MODEL = "m"


def test_a_build_asks_the_runtime_for_a_policed_run_in_the_worktree(tmp_path: Path) -> None:
    planning = tmp_path / "planning"
    make_installation(planning, git={"branch_prefix": "unit/"})
    specs = planning / "openspec"
    tree = tmp_path / "tree"
    runtime = StandInRuntime(answer="built it")

    answer = build_run(runtime=runtime, planning_repo=planning, allowed_tools="Read Edit")(
        "Implement it.", cwd=tree, model=models().implement
    )

    assert answer == "built it"
    request = runtime.request
    assert request.prompt == "Implement it."
    assert request.cwd == tree
    assert request.add_dirs == (specs,)
    assert request.policy == ToolPolicy(specs_dir=specs, branch_prefix="unit/")
    assert request.permission_mode == "edit"
    assert request.allowed_tools == "Read Edit"
    assert request.model == models().implement
    assert request.role == "implement"
    assert request.on_event is not None


def test_each_call_names_the_model_it_runs_on(tmp_path: Path) -> None:
    for model in (models().implement, models().rework):
        runtime = StandInRuntime()

        build_run(runtime=runtime)("Go.", cwd=tmp_path, model=model)

        assert runtime.request.role == "implement"
        assert runtime.request.model == model


def test_a_failed_build_raises_what_the_runtime_said(tmp_path: Path) -> None:
    """Half-finished edits are on disk: carrying on would commit them."""
    runtime = StandInRuntime(ok=False, error="the turn ended early")

    with pytest.raises(RuntimeError, match="^the turn ended early$"):
        build_run(runtime=runtime)("Implement it.", cwd=tmp_path, model=MODEL)


def test_a_review_asks_the_runtime_for_a_read_only_judgement(tmp_path: Path) -> None:
    runtime = StandInRuntime(answer='{"approved": true}')

    answer = build_run_review(runtime=runtime)(cwd=tmp_path)

    assert answer == '{"approved": true}'
    request = runtime.request
    assert request.prompt == REVIEW_PROMPT
    assert request.cwd == tmp_path
    assert request.allowed_tools == REVIEW_TOOLS
    assert request.model == models().review
    assert request.role == "review"


def test_a_review_is_told_what_happened_to_the_branch_first(tmp_path: Path) -> None:
    runtime = StandInRuntime()

    build_run_review(runtime=runtime)(cwd=tmp_path, context="MOVED ONTO A CHANGED PREDECESSOR")

    assert runtime.request.prompt == f"MOVED ONTO A CHANGED PREDECESSOR\n\n{REVIEW_PROMPT}"


def test_a_rework_s_review_is_asked_for_as_one(tmp_path: Path) -> None:
    runtime = StandInRuntime()

    build_run_review(runtime=runtime, model=models().rework_review, role="rework_review")(
        cwd=tmp_path
    )

    assert runtime.request.role == "rework_review"
    assert runtime.request.model == models().rework_review


def test_a_branch_that_moves_on_the_remote_during_an_agent_step_fails_the_step(
    tmp_path: Path,
) -> None:
    """Only the pipeline pushes, so a branch that moved under the agent was
    pushed by it — said at the step, not as a stale remote at the push."""
    make_installation(tmp_path / "planning")
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    tree = init_repo(tmp_path / "tree")
    git(tree, "remote", "add", "origin", str(remote))
    git(tree, "commit", "-q", "--allow-empty", "-m", "base")
    git(tree, "push", "-q", "origin", "main")
    branch = "spec/add-marker/1"
    git(tree, "checkout", "-q", "-b", branch)

    def push(request) -> None:
        git(tree, "commit", "-q", "--allow-empty", "-m", "work")
        git(tree, "push", "-q", "origin", branch)

    with pytest.raises(AgentPushed, match=branch):
        build_run(runtime=StandInRuntime(act=push))("Implement it.", cwd=tree, model=MODEL)


def _pushed_unit(tmp_path: Path) -> tuple[Path, Path, str]:
    """A worktree on a unit branch that is already pushed (a rework's state)."""
    make_installation(tmp_path / "planning")
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    tree = init_repo(tmp_path / "tree")
    git(tree, "remote", "add", "origin", str(remote))
    git(tree, "commit", "-q", "--allow-empty", "-m", "base")
    branch = "spec/add-marker/1"
    git(tree, "checkout", "-q", "-b", branch)
    git(tree, "push", "-q", "origin", "main", branch)
    return tree, remote, branch


def test_a_remote_that_cannot_be_read_after_the_step_does_not_fail_it(tmp_path: Path) -> None:
    tree, remote, _ = _pushed_unit(tmp_path)

    def lose_the_remote(request) -> None:
        remote.rename(tmp_path / "gone.git")

    runtime = StandInRuntime(answer="ok", act=lose_the_remote)

    assert build_run(runtime=runtime)("Go.", cwd=tree, model=MODEL) == "ok"


def test_a_remote_that_cannot_be_read_before_the_step_does_not_fail_it(tmp_path: Path) -> None:
    tree, remote, _ = _pushed_unit(tmp_path)
    gone = tmp_path / "gone.git"
    remote.rename(gone)

    def bring_it_back(request) -> None:
        gone.rename(remote)

    runtime = StandInRuntime(answer="ok", act=bring_it_back)

    assert build_run(runtime=runtime)("Go.", cwd=tree, model=MODEL) == "ok"


def test_a_push_from_elsewhere_during_the_step_is_not_the_agents(tmp_path: Path) -> None:
    tree, remote, branch = _pushed_unit(tmp_path)
    other = tmp_path / "other"
    subprocess.run(["git", "clone", "-q", "-b", branch, str(remote), str(other)], check=True)
    git(other, "config", "user.email", "person@example.com")
    git(other, "config", "user.name", "Person")

    def a_person_pushes(request) -> None:
        git(other, "commit", "-q", "--allow-empty", "-m", "a fix from the host")
        git(other, "push", "-q", "origin", branch)

    runtime = StandInRuntime(answer="ok", act=a_person_pushes)

    assert build_run(runtime=runtime)("Go.", cwd=tree, model=MODEL) == "ok"


def test_a_head_the_agent_only_fetched_is_not_the_agents_push(tmp_path: Path) -> None:
    """A person's newer head brought into the object store by a fetch is a
    commit this worktree has, but not one its own branch contains."""
    tree, remote, branch = _pushed_unit(tmp_path)
    other = tmp_path / "other"
    subprocess.run(["git", "clone", "-q", "-b", branch, str(remote), str(other)], check=True)
    git(other, "config", "user.email", "person@example.com")
    git(other, "config", "user.name", "Person")

    def a_person_pushes_and_the_agent_fetches(request) -> None:
        git(other, "commit", "-q", "--allow-empty", "-m", "a fix from the host")
        git(other, "push", "-q", "origin", branch)
        git(tree, "fetch", "-q", "origin")

    runtime = StandInRuntime(answer="ok", act=a_person_pushes_and_the_agent_fetches)

    assert build_run(runtime=runtime)("Go.", cwd=tree, model=MODEL) == "ok"


def test_a_step_that_leaves_the_remote_alone_is_not_failed(tmp_path: Path) -> None:
    make_installation(tmp_path / "planning")
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    tree = init_repo(tmp_path / "tree")
    git(tree, "remote", "add", "origin", str(remote))
    git(tree, "checkout", "-q", "-b", "spec/add-marker/1")

    assert build_run(runtime=StandInRuntime(answer="ok"))("Go.", cwd=tree, model=MODEL) == "ok"


def _noop(text: str) -> None:
    return None


def test_a_build_gives_the_journal_to_events_and_the_transcript_to_the_whole_text(
    tmp_path: Path,
) -> None:
    def journal(line: str) -> None:
        return None

    runtime = StandInRuntime()

    build_run(runtime=runtime, journal=journal, transcript=_noop)("Go.", cwd=tmp_path, model=MODEL)

    assert runtime.request.on_event is journal
    assert runtime.request.on_transcript is _noop


def test_a_review_gives_the_journal_to_events_and_the_transcript_to_the_whole_text(
    tmp_path: Path,
) -> None:
    def journal(line: str) -> None:
        return None

    runtime = StandInRuntime()

    build_run_review(runtime=runtime, journal=journal, transcript=_noop)(cwd=tmp_path)

    assert runtime.request.on_event is journal
    assert runtime.request.on_transcript is _noop


def test_every_agent_step_of_a_runner_carries_the_journal_and_the_transcript(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "planning"
    repo = RepoConfig(path=root / "checkouts" / "app", slug="example/app")
    installation = make_installation(root, repos={"app": repo.model_dump(mode="json")})
    agent = StandInRuntime(answer="ok")
    monkeypatch.setattr(runtimes, "active", lambda: agent)

    def journal(line: str) -> None:
        return None

    runner = build_runner(
        unit(),
        store=UnitStore(tmp_path / "units.json"),
        installation=installation,
        log=lambda _: None,
        journal=journal,
        transcript=_noop,
    )
    tree = tmp_path / "tree"
    tree.mkdir()

    runner.run("Implement.", cwd=tree, model=MODEL)
    runner.run_review(cwd=tree)
    runner.run_rework_review(cwd=tree)

    assert [r.role for r in agent.requests] == ["implement", "review", "rework_review"]
    assert all(r.on_transcript is _noop for r in agent.requests)
    assert all(r.on_event is journal for r in agent.requests)
