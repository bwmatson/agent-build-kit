"""The triggers that demote a review class: a revert of an auto-landed unit, and agreement below
the minimum over the most recent samples."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from agent_build_kit.config import ReviewConfig
from agent_build_kit.pipeline import demotion_record
from agent_build_kit.pipeline.audit_record import audit_results
from agent_build_kit.pipeline.review_outcome import Outcome
from agent_build_kit.pipeline.review_rates import sample_clean
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import UnitState
from agent_build_kit.pipeline.verdict import ReviewTier


def evaluate_demotions(
    units: Iterable[StoredUnit],
    *,
    verdicts: Path,
    audits: Path,
    demotions: Path,
    review: ReviewConfig,
    at: datetime,
    log: Callable[[str], None],
) -> None:
    """Demote each class with a reverted auto-landed unit, and each class listed in
    `review.auto_land.classes` whose agreement over its most recent `review.demotion.window`
    samples (ordered by the merge of their units) is below `review.demotion.min_agreement`. An
    error evaluating one class is logged and the others are still evaluated."""
    if not verdicts.exists():
        return
    records: dict[str, dict[str, Any]] = json.loads(verdicts.read_text())
    merged_at = {u.id: _merged_at(u) for u in units if u.state is UnitState.MERGED}
    results = audit_results(audits)

    def demote(unit_class: str, trigger: str, unit: str) -> None:
        demotion_record.demote(
            demotions, unit_class=unit_class, trigger=trigger, unit=unit, at=at, say=log
        )

    for unit, record in sorted(records.items()):
        if not (record.get("final") and record.get("auto_landed")):
            continue
        if record.get("outcome") != Outcome.REVERTED or _recorded(demotions, record, unit):
            continue
        try:
            demote(record["unit_class"], "revert", unit)
        except Exception as error:  # noqa: BLE001
            log(f"{record.get('unit_class')}: revert of {unit} not evaluated — {error}")

    for unit_class in review.auto_land.classes:
        try:
            _agreement(unit_class, records, merged_at, results, demotions, review, demote)
        except Exception as error:  # noqa: BLE001
            log(f"{unit_class}: agreement not evaluated — {error}")


def _merged_at(unit: StoredUnit) -> str:
    stamps = [entry["at"] for entry in unit.history if entry.get("state") == "merged"]
    return max(stamps, default="")


def _recorded(demotions: Path, record: dict[str, Any], unit: str) -> bool:
    """Whether the class's standing demotion already names this unit as a trigger."""
    standing = demotion_record.read_demotions(demotions).get(record["unit_class"])
    return (
        standing is not None
        and standing.get("lifted") is None
        and any(t["unit"] == unit for t in standing["triggers"])
    )


def _agreement(
    unit_class: str,
    records: dict[str, dict[str, Any]],
    merged_at: dict[str, str],
    results: dict[str, str],
    demotions: Path,
    review: ReviewConfig,
    demote: Callable[[str, str, str], None],
) -> None:
    if unit_class in demotion_record.demoted_classes(demotions):
        return
    samples = sorted(
        (merged_at[unit], unit, clean)
        for unit, record in records.items()
        if record.get("final")
        and record.get("unit_class") == unit_class
        and record.get("brief")
        and record.get("evidence_tier") == ReviewTier.AUTO
        and unit in merged_at
        and (clean := sample_clean(unit, record, results)) is not None
    )
    window = review.demotion.window
    recent = samples[-window:]
    if len(recent) < min(window, review.auto_land.min_samples):
        return
    if sum(clean for _, _, clean in recent) / len(recent) < review.demotion.min_agreement:
        demote(unit_class, "agreement", recent[-1][1])
