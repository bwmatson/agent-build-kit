"""What the tests of a lane run's usage guard share: a unit in review told its base moved, whose
move meets a conflict the resolver's steps cannot settle, over a runtime with a usage window and
the real guard reading the faked usage endpoint (`tests/usage_host.py`).

The scene is `test_restack_lane_prepare`'s. `Failing` stands at the edge of `restack_onto`: given
the resolver `prepare` builds it asks it twice and reports the conflict they could not settle, so a
run asks the guard for each of the resolver's two calls, the port and the review of the result.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit import runtimes
from agent_build_kit.pipeline import usage_guard
from agent_build_kit.pipeline.wiring import build_usage_gate
from agent_build_kit.runtimes import AgentRateLimited, AgentRequest, AgentResult
from tests.graph.agent_fakes import distinct_models
from tests.graph.test_adapt_in_the_restack_session import MISSING, Failing
from tests.graph.test_restack_lane_prepare import Scene
from tests.graph.test_session_continuation import Sessions, agents
from tests.restack_lane_fakes import asked_of_the_guard
from tests.tick_driver import Setup, make_setup
from tests.usage_host import Host, payload

MINUTE = timedelta(minutes=1)
RESOLVER_CALLS = 2  # what `Failing` asks of the resolver


class Windowed(Sessions):
    """A runtime with a usage window. `after` hears the number of each call that finished, and a
    call from number `refusing_from` is refused by the model itself."""

    supports_usage_tracking = True

    def __init__(
        self,
        *,
        verdicts: Sequence[str] = (),
        after: Callable[[int], None] = lambda number: None,
        refusing_from: int = 0,
    ) -> None:
        super().__init__(verdicts=verdicts)
        self.after = after
        self.refusing_from = refusing_from

    def run(self, request: AgentRequest) -> AgentResult:
        if self.refusing_from and len(self.requests) + 1 >= self.refusing_from:
            self.requests.append(request)
            raise AgentRateLimited("the model is at its limit")
        result = super().run(request)
        self.after(len(self.requests))
        return result


class Lane:
    """The scene with its conflict, its runtime and every decision of the guard."""

    def __init__(
        self,
        graph: Setup,
        host: Host,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        runtime: Windowed,
    ) -> None:
        distinct_models()
        self.graph = graph
        self.runtime = runtime
        self.host = host
        self.scene = Scene(graph, tmp_path)
        monkeypatch.setattr(runtimes, "active", lambda: runtime)
        host.keep_in(graph.inst.state_dir)
        # Before the gate is built, which takes the guard's decision as it stands.
        self.decisions: list[usage_guard.Decision] = asked_of_the_guard(monkeypatch)
        may_start, resume_at = build_usage_gate()
        graph.options.update(agents(runtime), may_start=may_start, resume_at=resume_at)
        graph.options["restack_onto"] = self.scene.restack(Failing())
        graph.options["reset_to"] = lambda tree, onto, keep: None
        graph.options["tests_in"] = lambda tree: {MISSING}
        graph.options["tests_changed"] = lambda tree, ref: set()
        self.scene.told_its_base_moved()

    def shut(self) -> None:
        """The session read 99% a moment ago against a pause at 70."""
        self.host.keep_reading(MINUTE // 2, payload(session=99.0, weekly=5.0))

    def open(self) -> None:
        self.host.keep_reading(MINUTE // 2, payload(session=10.0, weekly=5.0))


@pytest.fixture
def make_lane(host: Host, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[..., Lane]:
    """The lane's scene over a tick set up after the usage host, so the installation's
    configuration is the one in force; `Windowed` arguments say what the runtime does."""

    def make(**runtime: Any) -> Lane:
        return Lane(
            make_setup(tmp_path, monkeypatch), host, monkeypatch, tmp_path, Windowed(**runtime)
        )

    return make
