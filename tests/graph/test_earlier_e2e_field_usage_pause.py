"""A thread saved before the e2e fields were renamed, and paused at the usage gate, still
routes through e2e-test when the window opens: the resume re-enters its node without
passing `prepare` or an event."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.graph.checkpointer import unit_graphs_path
from agent_build_kit.graph.state import Node
from agent_build_kit.pipeline.unit_store import UnitStore
from tests.factories import unit
from tests.graph.test_earlier_e2e_field_checkpoint import saved_under_the_old_field_names
from tests.graph_driver import position, tick
from tests.runner_fakes import Recorder


def test_a_thread_paused_before_review_under_the_old_field_names_runs_e2e_test_on_resume(
    tmp_path: Path,
) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(tier="e2e-test")])
    recorder = Recorder(store)
    window = iter([(True, "")] * 2)  # the tests and the implementation, then the window closes
    tick(
        tmp_path,
        recorder,
        tier="e2e-test",
        may_start=lambda: next(window, (False, "session usage at 88%")),
    )
    assert position(tmp_path).next == (Node.REVIEW,)
    assert "review" not in recorder.events
    saved_under_the_old_field_names(unit_graphs_path(tmp_path / "state"))

    tick(tmp_path, recorder, tier="e2e-test", may_start=lambda: (True, ""))

    assert recorder.events.index("review") < recorder.events.index("e2e-test")
    assert position(tmp_path).next == (Node.AWAIT_REVIEW,)
