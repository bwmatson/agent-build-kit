"""The e2e-test step reads the unit's base through the one resolution every other step uses: the
remote's trunk for a trunk base and the branch itself for a unit's branch. The bare name stays the
rebase's and the pull request's (spec: unit-own-tests)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_build_kit.pipeline.stack_runner import RunStatus
from tests.graph.test_build_path import build
from tests.graph.test_remaining_paths import CLEAN, Moves, fresh
from tests.runner_fakes import Recorder

TRUNK = "dev"
PARENT = "spec/add-marker/0"


class Seen:
    """The base each call that reads git in the e2e-test step was given, and the one the pull
    request was opened on."""

    def __init__(self, recorder: Recorder) -> None:
        self.recorder = recorder
        self.scope: list[str] = []
        self.run: list[str] = []
        self.pr: list[str] = []
        self.fail_when_moved = False

    def runs_whole(self, *, cwd: Path, base: str) -> bool:
        self.scope.append(base)
        return False

    def e2e(self, *, cwd: Path, base: str | None = None) -> tuple[bool, str]:
        self.run.append(base or "")
        ok, output = self.recorder.e2e(cwd=cwd, base=base)
        # The run on the moved commit is the second; it is the one that fails when asked to.
        return ok and not (self.fail_when_moved and len(self.run) > 1), output

    def open_pr(self, unit: Any, *, body: str, base: str, cwd: Path, **bodies: str) -> int:
        self.pr.append(base)
        return self.recorder.open_pr(unit, body=body, base=base, cwd=cwd, **bodies)

    def overrides(self) -> dict[str, Any]:
        return {
            "e2e_runs_whole": self.runs_whole,
            "run_e2e": self.e2e,
            "open_pr": self.open_pr,
        }


def e2e_unit(tmp_path: Path, **options: Any) -> Seen:
    return Seen(fresh(tmp_path, tier="e2e-test", **options))


def test_a_unit_on_the_trunk_hands_the_scope_and_the_run_the_remotes_trunk(
    tmp_path: Path,
) -> None:
    seen = e2e_unit(tmp_path)

    outcome = build(tmp_path, seen.recorder, base=TRUNK, **seen.overrides())

    assert outcome.status == RunStatus.OPEN, outcome
    assert seen.scope == [f"origin/{TRUNK}"]
    assert seen.run == [f"origin/{TRUNK}"]


def test_the_pull_request_keeps_the_bare_trunk_name(tmp_path: Path) -> None:
    seen = e2e_unit(tmp_path)

    build(tmp_path, seen.recorder, base=TRUNK, **seen.overrides())

    assert seen.pr == [TRUNK]


def test_a_failure_after_a_move_sends_the_unit_back_to_rebase_on_the_bare_trunk_name(
    tmp_path: Path,
) -> None:
    seen = e2e_unit(tmp_path)
    seen.fail_when_moved = True
    moves = Moves(seen.recorder, CLEAN)

    build(tmp_path, seen.recorder, base=TRUNK, **seen.overrides(), **moves.overrides())

    assert seen.run[:2] == [f"origin/{TRUNK}"] * 2
    log = " ".join(seen.recorder.logged)
    assert f"held: base moved before its push: e2e-test failed on {TRUNK}; resuming at" in log
    assert f"restack on {TRUNK}" in log
    assert "origin/" not in log


def test_a_unit_stacked_on_a_parents_branch_hands_that_branch(tmp_path: Path) -> None:
    seen = e2e_unit(tmp_path)

    build(tmp_path, seen.recorder, base=PARENT, **seen.overrides())

    assert seen.scope == [PARENT]
    assert seen.run == [PARENT]
    assert seen.pr == [PARENT]
