"""A person's requeue of a unit held for its size waives the size (spec: hold-and-split,
a unit that cannot be split, or has no rounds left, is held for a person)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.config import CeilingsConfig
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_store import REQUEUE_BY, Cause, HeldBy, UnitStore
from agent_build_kit.pipeline.units import HELD
from agent_build_kit.pipeline.verdict import GroupText, ReviewTier, compute_verdict
from tests.conftest import make_installation
from tests.factories import unit
from tests.verdict_support import green_facts

UNIT_ID = "a/1"


def held_unit(tmp_path: Path, cause: Cause, held_by: HeldBy) -> tuple[Installation, UnitStore]:
    inst = make_installation(tmp_path)
    store = cli.store_for(inst)
    store.upsert([unit(UNIT_ID)], change="a")
    store.set_state(UNIT_ID, HELD, cause=cause, held_by=held_by, branch="spec/a/1")
    return inst, store


def person_requeues(inst: Installation) -> int:
    return cli.requeue(inst, UNIT_ID, "resume", say=lambda *a, **k: None, by=REQUEUE_BY)


def test_a_requeue_of_a_unit_held_for_a_person_for_its_size_records_the_waiver(
    tmp_path: Path,
) -> None:
    inst, store = held_unit(tmp_path, Cause.TOO_BIG_FOR_TIER, HeldBy.REVIEW)

    assert person_requeues(inst) == 0

    assert store.get(UNIT_ID).size_waived is True


def test_a_requeue_of_a_unit_held_for_another_reason_records_nothing_beside_it(
    tmp_path: Path,
) -> None:
    sized, sized_store = held_unit(tmp_path / "sized", Cause.TOO_BIG_FOR_TIER, HeldBy.REVIEW)
    other, other_store = held_unit(tmp_path / "other", Cause.NEEDS_HUMAN, HeldBy.REVIEW)

    assert person_requeues(sized) == 0
    assert person_requeues(other) == 0

    assert sized_store.get(UNIT_ID).size_waived is True
    assert other_store.get(UNIT_ID).size_waived is False


def test_the_next_reviews_verdict_skips_the_size_step(tmp_path: Path) -> None:
    inst, store = held_unit(tmp_path, Cause.TOO_BIG_FOR_TIER, HeldBy.REVIEW)
    person_requeues(inst)
    facts = green_facts(
        planned_estimate=ReviewTier.AUTO,
        classification=ReviewTier.FULL,
        changed_lines=5000,
        groups=(GroupText(number=1, text="task"),),
        size_waived=store.get(UNIT_ID).size_waived,
    )

    result = compute_verdict(facts, ceilings=CeilingsConfig(), buffer=0.2)

    assert result.split is None
    assert result.tier is ReviewTier.FULL


def test_the_waiver_survives_a_restart(tmp_path: Path) -> None:
    inst, store = held_unit(tmp_path, Cause.TOO_BIG_FOR_TIER, HeldBy.REVIEW)
    person_requeues(inst)

    assert UnitStore(store.path).get(UNIT_ID).size_waived is True


def test_a_refused_requeue_records_no_waiver(tmp_path: Path) -> None:
    inst, store = held_unit(tmp_path, Cause.TOO_BIG_FOR_TIER, HeldBy.REVIEW)

    code = cli.requeue(inst, UNIT_ID, "rework", say=lambda *a, **k: None, by=REQUEUE_BY)

    assert code == 1
    assert store.get(UNIT_ID).size_waived is False
