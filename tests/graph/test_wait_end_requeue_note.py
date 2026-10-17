"""The reason a wait's end gives the requeue event is what the thread's wait node writes into
the unit's history, so the note a person reads is the one the pipeline meant."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.graph.state import EventKind, Node, ResumeEvent
from agent_build_kit.pipeline.unit_store import RequeueReason
from tests.factories import unit
from tests.graph_driver import fresh, position, tick

REASON = "its wait ended (waiting on base group 1 is now merged)"


def test_the_wait_node_records_the_wait_ended_reason_as_the_history_note(tmp_path: Path) -> None:
    recorder = fresh(tmp_path)
    tick(tmp_path, recorder)
    tick(tmp_path, recorder, event=ResumeEvent(kind=EventKind.HOLD))

    tick(
        tmp_path,
        recorder,
        event=ResumeEvent(kind=EventKind.REQUEUE, requeue=RequeueReason.RESUME, reason=REASON),
    )

    assert position(tmp_path).next == (Node.PREPARE,)
    assert recorder.store.get(unit().id).history[-1]["note"] == f"requeue: {REASON}"
