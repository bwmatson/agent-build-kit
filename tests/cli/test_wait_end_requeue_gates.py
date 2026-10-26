"""The automatic requeue when a wait ends re-checks the unit's dependencies as it requeues, so a
`Needs:` the wait did not record still holds the unit (spec: resume-gating)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import IN_REVIEW, PLANNED
from tests.factories import new_unit
from tests.wait_end_support import CHILD, PARENT, Pipeline, pipeline, save_failure

OTHER = "other/1"


@pytest.fixture
def pipe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Pipeline:
    return pipeline(tmp_path, monkeypatch)


def add_unrecorded_merge_need(pipe: Pipeline) -> None:
    """Make the thread's delivery be followed by a `Needs: ... merged` on OTHER, a unit of
    another repository in review that the recorded wait did not name."""
    delivered = pipe.host.resume_thread

    def resume(inst: Any, unit: Any, kind: str, **kwargs: Any) -> Any:
        resumed = delivered(inst, unit, kind, **kwargs)
        pipe.store.set_merge_needs(unit.id, (OTHER,))
        return resumed

    pipe.host.resume_thread = resume  # type: ignore[method-assign]


def test_a_unit_whose_wait_ended_stays_gated_while_a_dependency_it_did_not_record_is_unmet(
    pipe: Pipeline, monkeypatch: pytest.MonkeyPatch
) -> None:
    pipe.store.upsert(
        [new_unit(PARENT), new_unit(OTHER, repo="platform"), new_unit(CHILD, depends_on=(PARENT,))]
    )
    pipe.store.set_state(OTHER, IN_REVIEW, pr=2, branch=f"spec/{OTHER}")
    pipe.store.set_state(PARENT, IN_REVIEW, pr=1, branch=f"spec/{PARENT}")
    save_failure(pipe)
    pipe.pass_()
    assert pipe.store.get(CHILD).waited_on == (PARENT,)

    add_unrecorded_merge_need(pipe)
    monkeypatch.setattr(cli, "resume_thread", pipe.host.resume_thread)
    pipe.merge()
    pipe.pass_()

    child = pipe.store.get(CHILD)
    assert (child.state, child.cause) == (PLANNED, Cause.GATED)
    assert "waiting for other group 1 to merge" in child.note
