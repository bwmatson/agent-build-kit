"""Each call of the restack's conflict step is one `restack` row in the usage ledger, in a
run and in a stack move, naming the unit being moved, its change and repo, and the session
the calls share (spec: restack-conflicts, each call is recorded as the restack node).

The runtime reports each call it finishes with the session it ran in, as a real one does.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.usage_ledger import UsageRecord, read_ledger
from agent_build_kit.runtimes import AgentRequest, AgentResult
from tests.factories import unit
from tests.graph.test_build_path import build
from tests.graph.test_restack_step_in_prepare import Settling
from tests.graph.test_session_continuation import Sessions, agents
from tests.graph_driver import fresh
from tests.restack_turn_fakes import Rig, keeps_both
from tests.runtimes.stand_in import StandInRuntime


class Numbered(StandInRuntime):
    """A runtime that opens a new session for a call that continues none, and reports
    the call it finishes, as the ledger's recorder is told."""

    name = "numbered"
    supports_session_resume = True

    def __init__(self, **kw) -> None:
        super().__init__(**kw)
        self.opened = 0

    def run(self, request: AgentRequest) -> AgentResult:
        result = super().run(request)
        if request.resume_session:
            session = request.resume_session
        else:
            self.opened += 1
            session = f"sess-{self.opened}"
        result = result.model_copy(update={"session_id": session})
        if request.on_result:
            request.on_result(result)
        return result


def restack_rows(installation: Installation) -> list[UsageRecord]:
    ledger = installation.state_dir / "usage-ledger.jsonl"
    return [r for r in read_ledger(ledger) if r.node == "restack"]


def test_a_two_call_conflict_in_a_run_writes_two_rows_in_one_session(
    tmp_path: Path, workspace: Installation
) -> None:
    recorder = fresh(tmp_path)

    build(tmp_path, recorder, restack_onto=Settling(), **agents(Sessions()))

    first, second = restack_rows(workspace)
    assert (first.unit, first.change, first.repo) == (unit().id, unit().change, unit().repo)
    assert (second.unit, second.change, second.repo) == (first.unit, first.change, first.repo)
    assert first.session_id == second.session_id == "sess-1"
    # A call of the unit's build session in a run: its role and the unit's tier are filled.
    assert (first.role, second.role) == ("implement", "implement")
    assert (first.tier, second.tier) == (unit().tier, unit().tier)


@pytest.fixture
def rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Rig:
    made = Rig(tmp_path, monkeypatch)
    made.runtime = Numbered
    return made


def test_a_stack_moves_calls_are_recorded_as_restack_for_the_child(rig: Rig) -> None:
    calls: list[AgentRequest] = []

    def drops_then_keeps(request: AgentRequest) -> None:
        calls.append(request)
        cwd = request.cwd or rig.repo
        if len(calls) == 1:
            (cwd / "markers.py").write_text('markers = ["integration"]\n')
        else:
            keeps_both(cwd)

    rig.act = drops_then_keeps

    rig.restack()

    rows = restack_rows(rig.installation)
    assert len(rows) == 2
    assert {(r.unit, r.change, r.repo) for r in rows} == {
        (rig.child.id, rig.child.change, rig.child.repo)
    }
    assert rows[0].session_id == rows[1].session_id, "the calls are one session"
    # Made outside a run: the generic role and no tier, which is what a run's rows differ by.
    assert {(r.role, r.tier) for r in rows} == {("generic", "")}
