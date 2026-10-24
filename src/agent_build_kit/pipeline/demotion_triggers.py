"""The triggers that demote a review class: a revert of an auto-landed unit, agreement below the
minimum over the most recent samples, a failed verify of a change holding an auto-landed unit,
and a failed audit."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from agent_build_kit.config import ReviewConfig
from agent_build_kit.pipeline import audit_record, demotion_record
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
        _demote(demotions, unit_class, trigger, unit, at, log)

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


def _demote(
    demotions: Path,
    unit_class: str,
    trigger: str,
    unit: str,
    at: datetime,
    log: Callable[[str], None],
) -> None:
    """Record the trigger, and say so when it makes a new demotion (a second trigger on a class
    already demoted is said by the record)."""
    if demotion_record.demote(
        demotions, unit_class=unit_class, trigger=trigger, unit=unit, at=at, say=log
    ):
        log(f"{unit_class}: demoted by {trigger} on {unit}")


def _merged_at(unit: StoredUnit) -> str:
    stamps = [entry["at"] for entry in unit.history if entry.get("state") == "merged"]
    return max(stamps, default="")


def _recorded(demotions: Path, record: dict[str, Any], unit: str) -> bool:
    """Whether the class's demotion, standing or lifted, already names this unit as a trigger,
    so a lift is not undone by the evidence it was made over."""
    held = demotion_record.read_demotions(demotions).get(record["unit_class"])
    return held is not None and any(
        t["unit"] == unit for t in [*held["triggers"], *held.get("earlier", [])]
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
    held = demotion_record.read_demotions(demotions).get(unit_class, {})
    if held and held.get("lifted") is None:
        return
    # Evidence older than a lift was weighed by the person who lifted it.
    lifted = held.get("lifted")
    since = datetime.fromisoformat(lifted) if lifted else None
    samples = sorted(
        (merged_at[unit], unit, clean)
        for unit, record in records.items()
        if record.get("final")
        and record.get("unit_class") == unit_class
        and record.get("brief")
        and record.get("evidence_tier") == ReviewTier.AUTO
        and unit in merged_at
        and (since is None or datetime.fromisoformat(merged_at[unit]) > since)
        and (clean := sample_clean(unit, record, results)) is not None
    )
    window = review.demotion.window
    recent = samples[-window:]
    if len(recent) < min(window, review.auto_land.min_samples):
        return
    if sum(clean for _, _, clean in recent) / len(recent) < review.demotion.min_agreement:
        demote(unit_class, "agreement", recent[-1][1])


def demote_for_failed_verify(
    change: str,
    units: Iterable[StoredUnit],
    *,
    verdicts: Path,
    demotions: Path,
    at: datetime,
    log: Callable[[str], None],
) -> None:
    """Demote the class of each auto-landed unit of `change`, with the trigger `verify`, since
    the live test cannot say which unit broke it. Any error is logged and swallowed."""
    try:
        if not verdicts.exists():
            return
        records: dict[str, dict[str, Any]] = json.loads(verdicts.read_text())
        for unit in sorted(u.id for u in units if u.carries(change)):
            record = records.get(unit, {})
            if record.get("final") and record.get("auto_landed"):
                _demote(demotions, record["unit_class"], "verify", unit, at, log)
    except Exception as error:  # noqa: BLE001
        log(f"{change}: demotion for the failed verify not evaluated — {error}")


def demote_for_failed_audit(
    unit: str,
    *,
    audits: Path,
    demotions: Path,
    at: datetime,
    log: Callable[[str], None],
) -> None:
    """Demote the class recorded for the audited unit with the trigger `audit`. Any error is
    logged and swallowed."""
    try:
        unit_class = audit_record.read_audits(audits)[unit]["unit_class"]
        _demote(demotions, unit_class, "audit", unit, at, log)
    except Exception as error:  # noqa: BLE001
        log(f"{unit}: demotion for the failed audit not evaluated — {error}")
