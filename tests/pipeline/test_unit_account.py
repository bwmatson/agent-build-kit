"""A unit's agent calls carry its repo's resolved account; planning carries none, and a stored
session made under another account is not resumed (spec: claude-accounts)."""

from __future__ import annotations

import json
from functools import partial
from pathlib import Path

import pytest

from agent_build_kit import claude_account, runtimes
from agent_build_kit.config import CLAUDE_CODE, RepoConfig
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import restack
from agent_build_kit.pipeline.planner import plan_round
from agent_build_kit.pipeline.restack import resolved_move
from agent_build_kit.pipeline.stack_runner import RunStatus
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.wiring import build_run, build_runner
from agent_build_kit.runtimes import AgentRequest
from agent_build_kit.settings import settings
from tests.conftest import make_installation
from tests.factories import commit, git, init_repo, unit
from tests.graph.test_agent_session import Sessions, killed_in_the_tests_step
from tests.graph_driver import tick
from tests.pipeline.test_planner_runtime import CHANGES, PLAN
from tests.runtimes.stand_in import StandInRuntime

MODEL = "m"


def labelled(root: Path, kit_home: Path | None) -> Installation:
    """`app` names the `kit` account; this machine gives the label `kit_home`, or no directory."""
    entry = {} if kit_home is None else {"config_dir": str(kit_home)}
    return make_installation(
        root,
        repos={
            "app": RepoConfig(
                path=root / "checkouts" / "app", slug="example/app", account="kit"
            ).model_dump(mode="json")
        },
        runtimes={CLAUDE_CODE: {"accounts": {"kit": entry}}},
    )


def requests_of_a_runner(
    tmp_path: Path, inst: Installation, monkeypatch: pytest.MonkeyPatch
) -> StandInRuntime:
    agent = StandInRuntime(answer="ok")
    monkeypatch.setattr(runtimes, "active", lambda: agent)
    runner = build_runner(
        unit(),
        store=UnitStore(tmp_path / "units.json"),
        installation=inst,
        log=lambda _: None,
    )
    tree = tmp_path / "tree"
    tree.mkdir()
    runner.run("Implement.", cwd=tree, model=MODEL)
    runner.run_review(cwd=tree)
    runner.run_rework_review(cwd=tree)
    return agent


def test_build_review_and_rework_review_carry_the_repos_account(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = labelled(tmp_path / "planning", tmp_path / "kit-home")
    expected = claude_account.resolve(inst, "kit")

    agent = requests_of_a_runner(tmp_path, inst, monkeypatch)

    assert [r.role for r in agent.requests] == ["implement", "review", "rework_review"]
    assert [r.account for r in agent.requests] == [expected] * 3
    assert expected.config_dir == tmp_path / "kit-home"


def test_a_label_with_no_directory_carries_the_default_account(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = labelled(tmp_path / "planning", None)

    agent = requests_of_a_runner(tmp_path, inst, monkeypatch)

    assert [r.account for r in agent.requests] == [claude_account.resolve(inst, None)] * 3


def test_a_planner_request_carries_no_account_beside_a_unit_that_does(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = labelled(tmp_path / "planning", tmp_path / "kit-home")
    planner = StandInRuntime(answer=json.dumps(PLAN))

    plan_round(changes=CHANGES, in_flight=[], runtime=planner)

    assert planner.request.account is None
    building = requests_of_a_runner(tmp_path, inst, monkeypatch)
    assert building.requests[0].account is not None


def keeps_both(request: AgentRequest) -> None:
    assert request.cwd is not None
    (request.cwd / "markers.py").write_text('markers = ["integration", "local_stack"]\n')


def test_a_restack_resolution_carries_the_moving_units_repo_account(tmp_path: Path) -> None:
    labelled(tmp_path / "planning", tmp_path / "kit-home")
    repo = init_repo(tmp_path / "repo")
    commit(repo, "markers.py", "markers = []\n")
    git(repo, "checkout", "-q", "-b", "spec/c/1")
    git(repo, "checkout", "-q", "-b", "spec/c/2")
    commit(repo, "markers.py", 'markers = ["local_stack"]\n')
    git(repo, "checkout", "-q", "main")
    commit(repo, "markers.py", 'markers = ["integration"]\n')
    runtime = StandInRuntime(act=keeps_both)

    resolved_move(
        repo,
        "spec/c/2",
        new_base="main",
        old_base="spec/c/1",
        moving_unit="add-marker/2",
        moving_intent="Register the local_stack marker",
        onto_unit="add-integration/1",
        onto_intent="Register the integration marker",
        moving_repo="app",
        resolve=partial(restack.claude_resolver, runtime=runtime),
    )

    account = runtime.request.account
    assert account is not None
    assert account.label == "kit"
    assert account.config_dir == tmp_path / "kit-home"


def resumed_under(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, made_under: Path, now_under: Path
) -> Sessions:
    """A node killed in session `sess-1` under `made_under`, run again under `now_under`."""
    tmp_path.mkdir()
    monkeypatch.setattr(settings, "claude_home", made_under)
    runtime = Sessions()
    recorder = killed_in_the_tests_step(tmp_path, runtime)

    monkeypatch.setattr(settings, "claude_home", now_under)
    outcome = tick(tmp_path, recorder, run=build_run(runtime=runtime))

    assert outcome.status == RunStatus.OPEN
    return runtime


def test_a_session_made_under_one_account_is_not_resumed_under_another(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = resumed_under(monkeypatch, tmp_path / "run", tmp_path / "a", tmp_path / "b")

    killed, again, *_ = runtime.requests
    assert again.resume_session == "", "no attempt to continue the other account's session"
    assert again.prompt == killed.prompt, "started afresh from the node's start"
