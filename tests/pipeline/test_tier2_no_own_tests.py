"""A tier 2 unit that adds or changes no tier 2 test runs no command, never takes the stack
lock, says so, and goes on as a unit whose tier 2 passed (spec: tier2-scope)."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as pipeline_cli
from agent_build_kit.pipeline.e2e import STATUS_CONTEXT, post_status, stack_lock
from agent_build_kit.profiles.python_uv import PythonUvProfile
from tests.conftest import make_installation
from tests.factories import unit
from tests.forges.stand_in import StandInForge
from tests.graph.test_build_path import build
from tests.graph.test_remaining_paths import fresh
from tests.tier2_scope_fakes import NEW, OLD, Ran, branch, session

SKIPPED = "tier 2 skipped: no tier 2 test added or changed"


def changes_no_test(tmp_path: Path) -> tuple[Path, str]:
    return branch(tmp_path, {"src/app.py": "x = 1\n"}, base_files={"tests/t.py": OLD})


def test_a_unit_that_changes_no_test_runs_no_command(tmp_path: Path) -> None:
    repo, base = changes_no_test(tmp_path)
    ran = Ran()

    ok, _ = session(tmp_path, ran).run(cwd=repo, base=base)

    assert ok
    assert ran.calls == []


def test_it_never_takes_the_stack_lock_so_a_held_one_does_not_make_it_wait(
    tmp_path: Path,
) -> None:
    repo, base = changes_no_test(tmp_path)
    gate = session(tmp_path, Ran(), timeout=0.1)

    with stack_lock(gate.lock, timeout=1, holder="another/1"):
        ok, _ = gate.run(cwd=repo, base=base)

    assert ok


def test_its_log_says_tier_2_was_skipped_and_why(tmp_path: Path) -> None:
    repo, base = changes_no_test(tmp_path)
    log: list[str] = []

    session(tmp_path, Ran(), log=log).run(cwd=repo, base=base)

    assert SKIPPED in log


def test_its_result_has_zero_tests_and_is_labelled_as_run_on_none(tmp_path: Path) -> None:
    repo, base = changes_no_test(tmp_path)
    gate = session(tmp_path, Ran())

    gate.run(cwd=repo, base=base)

    assert gate.result is not None
    assert gate.result.ran_no_tests
    assert (gate.result.passed, gate.result.failed, gate.result.skipped) == (0, 0, 0)
    assert gate.result.ok
    assert gate.verdict is None


def test_the_status_posted_for_its_commit_says_no_tier_2_test_ran(tmp_path: Path) -> None:
    repo, base = changes_no_test(tmp_path)
    gate = session(tmp_path, Ran())
    gate.run(cwd=repo, base=base)
    assert gate.result is not None
    forge = StandInForge()

    post_status(forge, forge.repo_id(), gate.result)

    [posted] = forge.statuses
    assert posted["context"] == STATUS_CONTEXT
    assert "no e2e-test ran" in posted["description"]
    assert "passed" not in posted["description"]


def test_the_snapshot_says_no_tier_2_test_ran_and_not_that_the_suite_passed(
    tmp_path: Path,
) -> None:
    repo, base = changes_no_test(tmp_path)

    _, snapshot = session(tmp_path, Ran()).run(cwd=repo, base=base)

    assert "no e2e-test ran" in snapshot
    assert "0 passed" not in snapshot


def test_the_unit_goes_on_as_one_whose_tier_2_passed(tmp_path: Path) -> None:
    repo, base = changes_no_test(tmp_path)
    ran = Ran()
    gate = session(tmp_path, ran)
    recorder = fresh(tmp_path, tier="tier2")

    outcome = build(
        tmp_path,
        recorder,
        base=base,
        worktree=lambda *args, **kwargs: repo,
        run_e2e=gate.run,
    )

    assert ran.calls == []
    assert outcome.status == "open"
    assert "push" in recorder.events
    assert recorder.store.get(unit().id).state == "in_review"


class TakesNoId(PythonUvProfile):
    """A profile none of whose commands takes any identifier."""

    def repeat_command(self, command: list[str], tests: list[str]) -> list[str] | None:
        return None


def test_a_changed_test_no_command_takes_runs_nothing_waits_for_no_lock_and_says_so(
    tmp_path: Path,
) -> None:
    repo, base = branch(tmp_path, {"tests/live/test_new.py": NEW}, base_files={"tests/t.py": OLD})
    ran = Ran()
    log: list[str] = []
    gate = session(tmp_path, ran, log=log, timeout=0.1, profile=TakesNoId())

    with stack_lock(gate.lock, timeout=1, holder="another/1"):
        ok, _ = gate.run(cwd=repo, base=base)

    assert ok
    assert ran.calls == []
    assert SKIPPED in log
    assert gate.result is not None
    assert gate.result.ran_no_tests


def test_the_node_says_no_test_ran_and_abk_status_does_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, base = changes_no_test(tmp_path)
    gate = session(tmp_path, Ran())
    recorder = fresh(tmp_path, tier="tier2")

    build(
        tmp_path,
        recorder,
        base=base,
        worktree=lambda *args, **kwargs: repo,
        run_e2e=gate.run,
        e2e_ran_no_tests=lambda: bool(gate.result and gate.result.ran_no_tests),
    )
    inst = make_installation(
        tmp_path, planning=dict(state_dir=".", worktree_root=str(tmp_path.parent / "trees"))
    )
    monkeypatch.setattr(pipeline_cli, "current_usage", lambda: None)
    assert pipeline_cli.cmd_status(argparse.Namespace(), inst) == 0

    shown = capsys.readouterr().out
    said = " | ".join(recorder.logged)
    assert "tier 2 ran no test" in said
    assert "tier 2 passed" not in said
    [line] = [
        line for line in shown.splitlines() if "  awaiting review:" in line or "  checking:" in line
    ]
    assert "no e2e-test ran" in line
    assert "passed" not in line
