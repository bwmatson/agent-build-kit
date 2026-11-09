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
from pathlib import Path
from typing import Any

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
OTHER = "other/1"


class Scene:
    """A repository whose `add-marker/1` branch conflicts with the trunk, an agent that keeps
    both sides, and a guard whose asks are noted with the thread they came from."""

    def __init__(
        self, host: Host, graph: Setup, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        self.graph = graph
        host.keep_in(graph.inst.state_dir)
        host.keep_reading(timedelta(seconds=30), payload(session=10.0, weekly=5.0))
        self.repo = init_repo(graph.inst.checkouts["app"])
        commit_file(self.repo, "markers.py", "markers = []\n")
        git(self.repo, "checkout", "-q", "-b", BRANCH)
        commit_file(self.repo, "markers.py", 'markers = ["e2e"]\n')
        git(self.repo, "checkout", "-q", "main")
        commit_file(self.repo, "markers.py", 'markers = ["integration"]\n')
        self.resolved: list[list[str]] = []
        self.asked: list[str] = []
        self.built: set[str] = set()
        self.building = threading.Event()

        runtime = Tracking(act=self.resolves)
        monkeypatch.setattr(runtimes, "active", lambda: runtime)
        graph.patch.setattr(cli, "build_restack", build_restack)
        real = usage_guard.decide_start

        def spy(**kwargs: Any) -> Decision:
            """The lane's ask is the guard's own; the tick's rounds are answered as the fixture
            does."""
            name = threading.current_thread().name
            self.asked.append(name)
            if name != "resolve":
                return Decision(may_start=True, reason="plenty")
            return real(**kwargs)

        for module in (usage_guard, wiring, cli):
            monkeypatch.setattr(module, "decide_start", spy)
        self.tree = graph.inst.state_dir / "tree"

    def resolves(self, request: AgentRequest) -> None:
        self.resolved.append(list(self.graph.recorder.events))
        keeps_both(request.cwd or self.repo)

    def moves(self, *results: Any, existing: int = 2) -> None:
        self.graph.options.update(Moves(self.graph.recorder, *results).overrides(existing=existing))

    def holds_main(self) -> bool:
        held = subprocess.run(
            ["git", "merge-base", "--is-ancestor", "main", BRANCH], cwd=self.repo, check=False
        )
        return held.returncode == 0


@pytest.fixture
def scene(host: Host, graph: Setup, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Scene:
    return Scene(host, graph, monkeypatch, tmp_path)


def test_a_run_that_settles_its_first_conflict_is_not_held_and_the_lane_is_not_asked(
    scene: Scene,
) -> None:
    scene.moves(RESOLVED)

    assert scene.graph.tick() == 0

    stored = scene.graph.store.get(UNIT)
    assert stored.state == IN_REVIEW
    assert all(entry.get("cause") != "base_changed" for entry in stored.history)
    assert scene.asked.count("resolve") == 0
    assert scene.resolved == []
