"""An environment treats input files that do not exist yet as absent (spec: project-init).

`sync` and `check` are the real child processes of the shared fake environment; the pipeline
is driven through `ensure` and what it says.
"""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.environment import ensure, prepare_worktree, problem, read_state
from tests.conftest import make_installation
from tests.environment_fakes import FakeEnvironment, repo_config


def installation(tmp_path: Path, env: FakeEnvironment) -> Installation:
    return make_installation(tmp_path / "planning", environment=env.config())


def test_a_missing_input_is_not_an_error_and_no_sync_depending_on_it_runs(tmp_path: Path) -> None:
    env = FakeEnvironment(tmp_path / "control", inputs=("web/manifest.toml",))
    env.fail_sync()
    said: list[str] = []

    ok = ensure(installation(tmp_path, env), say=said.append)

    assert ok
    assert "sync" not in env.calls()
    assert not any("failed" in line for line in said)


def test_an_input_that_appears_changes_the_hash_and_the_sync_runs(tmp_path: Path) -> None:
    env = FakeEnvironment(tmp_path / "control", inputs=("web/manifest.toml",))
    inst = installation(tmp_path, env)
    ensure(inst, say=lambda line: None)
    assert "sync" not in env.calls()
    recorded = read_state(inst.state_dir)

    (inst.root / "web").mkdir()
    (inst.root / "web" / "manifest.toml").write_text("name = 'web'\n")
    ensure(inst, say=lambda line: None)

    assert env.calls().count("sync") == 1
    state = read_state(inst.state_dir)
    assert state is not None and recorded is not None
    assert state.hash != recorded.hash


def test_problem_is_none_while_the_inputs_are_pending(tmp_path: Path) -> None:
    env = FakeEnvironment(tmp_path / "control", inputs=("web/manifest.toml",))
    env.break_it()
    inst = installation(tmp_path, env)

    assert problem(inst.root) is None
    assert "check" not in env.calls()


def test_a_worktree_with_only_missing_inputs_runs_no_sync_and_no_check(tmp_path: Path) -> None:
    env = FakeEnvironment(tmp_path / "control", inputs=("web/manifest.toml",))
    env.fail_sync()
    tree = tmp_path / "tree"
    tree.mkdir()

    fault = prepare_worktree(repo_config(tmp_path / "meta", env), tree, "main")

    assert fault is None
    assert env.calls() == []


def test_a_check_over_only_missing_inputs_reports_pending_not_unhealthy(tmp_path: Path) -> None:
    env = FakeEnvironment(tmp_path / "control", inputs=("web/manifest.toml",))
    env.break_it()
    inst = installation(tmp_path, env)
    said: list[str] = []

    ok = ensure(inst, say=said.append)

    assert ok
    assert any("pending" in line for line in said)
    assert not any("unhealthy" in line for line in said)
    state = read_state(inst.state_dir)
    assert state is not None and state.healthy
