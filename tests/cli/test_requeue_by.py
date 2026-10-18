"""A person's requeue is marked in the unit's history; the pipeline's own is not."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.unit_store import REQUEUE_BY, Cause
from agent_build_kit.pipeline.units import FAILED
from tests.conftest import make_installation
from tests.factories import unit


def requeued_entry(tmp_path: Path, **kw) -> dict:
    inst = make_installation(tmp_path)
    store = cli.store_for(inst)
    store.upsert([unit("a/1")], change="a")
    store.set_state("a/1", FAILED, cause=Cause.FAILED, branch="spec/a/1")

    assert cli.requeue(inst, "a/1", "resume", say=lambda *a, **k: None, **kw) == 0

    return store.get("a/1").history[-1]


def test_a_requeue_asked_for_by_a_person_is_marked(tmp_path: Path) -> None:
    assert requeued_entry(tmp_path, by=REQUEUE_BY)["by"] == REQUEUE_BY


def test_a_requeue_the_pipeline_makes_is_not(tmp_path: Path) -> None:
    entry = requeued_entry(tmp_path, because="its wait ended")

    assert entry["state"] == "planned"
    assert "by" not in entry
