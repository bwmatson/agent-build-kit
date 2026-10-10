"""A unit parked for a flake stays gated until the fix change has a unit and it has merged
(spec: flaky-tests)."""

from __future__ import annotations

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.flakes import wait_on_fix
from agent_build_kit.pipeline.unit_store import Cause, RequeueReason, UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, MERGED, PLANNED
from tests.factories import stored_unit
from tests.pipeline.test_flake_fix_change import change_with_unit, code_repo, flaked


def test_the_gate_holds_while_the_fix_change_has_no_unit_and_until_it_has_merged(
    installation: Installation,
) -> None:
    code_repo(installation)
    waiting = change_with_unit(installation, "feature", "feature/1")
    store = UnitStore(installation.root / "units.json")
    store.upsert([waiting])
    store.set_state(waiting.id, PLANNED, note="waiting for the fix", cause=Cause.GATED)
    store.set_gated_requeue(waiting.id, RequeueReason.RESUME)
    fix = str(wait_on_fix(installation, flaked(), waiting))

    def parked() -> tuple[object, ...]:
        cli.link_needs(installation, store=store)
        cli.release_gated(installation, store)
        held = store.get(waiting.id)
        return held.state, held.cause, held.gated_requeue

    held = (PLANNED, Cause.GATED, RequeueReason.RESUME)
    assert parked() == held, "the fix change is not planned yet, so nothing is merged"

    store.upsert([stored_unit(f"{fix}/1", change=fix, groups=(1,))])
    store.set_state(f"{fix}/1", IN_REVIEW, pr=3)
    assert parked() == held, "planned and in review is not merged"

    store.set_state(f"{fix}/1", MERGED, pr=3)
    assert parked()[2] is None, "released once the fix has merged"


def test_a_gate_on_a_change_that_is_no_longer_open_is_met(installation: Installation) -> None:
    code_repo(installation)
    waiting = change_with_unit(installation, "feature", "feature/1")
    store = UnitStore(installation.root / "units.json")
    store.upsert([waiting])
    store.set_state(waiting.id, PLANNED, note="waiting", cause=Cause.GATED)
    store.set_gated_requeue(waiting.id, RequeueReason.RESUME)
    fix = str(wait_on_fix(installation, flaked(), waiting))
    archive = installation.changes_dir / "archive"
    archive.mkdir()
    (installation.changes_dir / fix).rename(archive / f"2026-03-02-{fix}")

    cli.release_gated(installation, store)

    assert store.get(waiting.id).gated_requeue is None
