"""The restack `build_runner` gives a unit's run takes the repository's turn.

The wiring is the real one, over a real git repository, with a stand-in agent at
the runtime boundary. If `build_runner` stopped handing the restack the unit's
repo turn, the in-run rebase would go back to taking none.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import runtimes
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.wiring import build_runner
from agent_build_kit.runtimes import AgentRequest
from tests.conftest import make_installation
from tests.factories import unit
from tests.pipeline.test_restack_onto_before_push import BASE, BRANCH, Repos, stack
from tests.restack_turn_fakes import (
    around_the_resolver,
    mark_resolver,
    run_bounded,
    spy_git,
    writes_shared_state,
)
from tests.runtimes.stand_in import StandInRuntime


def test_a_units_restack_in_its_run_takes_the_repos_turn_through_the_real_wiring(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repos = Repos(tmp_path, edits_shared=True)
    stack(tmp_path)
    repos.advance_trunk(conflicting=True)
    installation = make_installation(
        tmp_path / "planning",
        repos={"app": {"path": str(repos.tree), "slug": "example/app"}},
        planning=dict(worktree_root=str(tmp_path / "trees")),
    )
    runner = build_runner(
        unit(),
        store=UnitStore(tmp_path / "units.json"),
        installation=installation,
        log=lambda _: None,
    )
    lock = installation.state_dir / "locks" / "repo-app.lock"
    calls = spy_git(monkeypatch, lock)

    def resolver(request: AgentRequest) -> None:
        assert request.cwd is not None
        mark_resolver(calls, lock, request.cwd)
        (request.cwd / "shared.py").write_text("value = 3\nvalue = 2\n")

    stand_in = StandInRuntime(act=resolver)
    monkeypatch.setattr(runtimes, "active", lambda: stand_in)

    moved = run_bounded(
        lambda: runner.restack_onto(tree=repos.tree, branch=BRANCH, base=BASE, unit=unit())
    )

    assert moved is not None and moved.resolved == ("shared.py",)
    before, during, after = around_the_resolver(calls)
    assert not during.held
    assert any(c.verb[:2] == ("rebase", "--onto") and c.held for c in before)
    assert any(c.verb[:2] == ("rebase", "--continue") and c.held for c in after)
    assert [c.verb for c in calls if writes_shared_state(c) and not c.held] == []
