"""A run that finds its base moved twice holds its unit planned for the moved base, and the
lane moves it at once, its conflict step asked of the usage guard like any agent step.

The run is driven through `abk tick` over the fake runner (`tests/tick_driver.py`), whose
`restack_onto` finds a conflict before each push as `tests/graph/test_remaining_paths.py`'s
`Moves` does. The lane's stack move is the pipeline's own, over a real repository whose branch
conflicts with the trunk, with the usage endpoint faked at the HTTP boundary.
"""

from __future__ import annotations

import subprocess
import threading
from datetime import timedelta

import pytest

from agent_build_kit import runtimes
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline import usage_guard, wiring
from agent_build_kit.pipeline.events import build_restack
from agent_build_kit.pipeline.units import IN_REVIEW
from agent_build_kit.pipeline.usage_guard import Decision
from agent_build_kit.runtimes import AgentRequest
from tests.factories import git, init_repo
from tests.graph.test_remaining_paths import RESOLVED, Moves
from tests.restack_lane_fakes import Tracking
from tests.restack_turn_fakes import commit_file, keeps_both
from tests.tick_driver import UNIT, Setup
from tests.usage_host import Host, payload

BRANCH = "spec/add-marker/1"


def test_a_run_held_for_a_second_moved_base_is_moved_by_the_lane_with_its_conflict_step_gated(
    host: Host, graph: Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    host.keep_in(graph.inst.state_dir)
    host.keep_reading(timedelta(seconds=30), payload(session=10.0, weekly=5.0))
    repo = init_repo(graph.inst.checkouts["app"])
    commit_file(repo, "markers.py", "markers = []\n")
    git(repo, "checkout", "-q", "-b", BRANCH)
    commit_file(repo, "markers.py", 'markers = ["local_stack"]\n')
    git(repo, "checkout", "-q", "main")
    commit_file(repo, "markers.py", 'markers = ["integration"]\n')
    resolved: list[list[str]] = []

    def resolves(request: AgentRequest) -> None:
        resolved.append(list(graph.recorder.events))
        keeps_both(request.cwd or repo)

    runtime = Tracking(act=resolves)
    monkeypatch.setattr(runtimes, "active", lambda: runtime)
    graph.patch.setattr(cli, "build_restack", build_restack)
    asked: list[str] = []
    real = usage_guard.decide_start

    def spy(**kwargs):
        """The lane's ask is the guard's own; the tick's rounds are answered as the fixture does."""
        name = threading.current_thread().name
        asked.append(name)
        if name != "restack":
            return Decision(may_start=True, reason="plenty")
        return real(**kwargs)

    for module in (usage_guard, wiring, cli):
        monkeypatch.setattr(module, "decide_start", spy)
    # The push-time move, the resumed run's own restack, its push-time move.
    graph.options.update(Moves(graph.recorder, RESOLVED, None, RESOLVED).overrides(existing=2))

    assert graph.tick() == 0

    assert len(resolved) == 1
    assert "push" not in resolved[0], "moved from the hold, before the unit was built again"
    assert asked.count("restack") == 1, "the lane's conflict step is asked of the guard"
    held = subprocess.run(["git", "merge-base", "--is-ancestor", "main", BRANCH], cwd=repo)
    assert held.returncode == 0
    assert graph.store.get(UNIT).state == IN_REVIEW, "then built, in a worker"
