"""The sweep that keeps the outcome of each merged unit current until the recheck horizon."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from agent_build_kit.forges.base import Forge, RepoId
from agent_build_kit.pipeline.file_lock import atomic_write_text, file_lock
from agent_build_kit.pipeline.review_outcome import with_outcome
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import UnitState

# Days a merged unit is rechecked for a revert; its outcome is final after that.
HORIZON_DAYS = 14

# What the derivation adds to a verdict record.
OUTCOME_FIELDS = ("outcome", "reworks", "revert_checked")


def sweep_outcomes(
    units: Iterable[StoredUnit],
    *,
    verdicts: Path,
    forge_of: Callable[[str], tuple[Forge, RepoId]],
    checkouts: Mapping[str, Path],
    trunks: Mapping[str, str],
    now: datetime,
    log: Callable[[str], None],
) -> None:
    """Derive the outcome of each unit merged within `HORIZON_DAYS` of `now` whose verdict record
    is final, and write them over the records at `verdicts` once, atomically, and only when one
    changed. The forge and the checkout are asked without the lock the recording holds, and the
    file is read again under it, so a verdict recorded meanwhile is kept. A unit whose forge or
    checkout cannot be read is logged and the others are still derived."""
    if not verdicts.exists():
        return
    records: dict[str, dict[str, Any]] = json.loads(verdicts.read_text())
    derived: dict[str, dict[str, Any]] = {}
    for unit in units:
        if not _is_final(records.get(unit.id)) or not _inside_horizon(unit, now):
            continue
        try:
            forge, repo = forge_of(unit.repo)
            alone = with_outcome(
                {unit.id: records[unit.id]},
                unit,
                forge=forge,
                repo=repo,
                checkout=checkouts[unit.repo],
                trunk=trunks[unit.repo],
            )
        except Exception as error:  # noqa: BLE001
            log(f"outcome of {unit.id} not derived — {type(error).__name__}: {error}")
            continue
        derived[unit.id] = {k: v for k, v in alone[unit.id].items() if k in OUTCOME_FIELDS}
    if not derived:
        return
    with file_lock(verdicts.with_name(f"{verdicts.name}.lock")):
        current: dict[str, dict[str, Any]] = json.loads(verdicts.read_text())
        merged = {
            uid: {**record, **derived[uid]} if uid in derived and _is_final(record) else record
            for uid, record in current.items()
        }
        if merged != current:
            atomic_write_text(verdicts, json.dumps(merged, indent=2, sort_keys=True))


def _is_final(record: Mapping[str, Any] | None) -> bool:
    return record is not None and record.get("final") is True


def _inside_horizon(unit: StoredUnit, now: datetime) -> bool:
    """Whether the unit is merged and its merge, the latest `merged` history entry, is no
    older than the horizon."""
    if unit.state is not UnitState.MERGED:
        return False
    stamps = [entry["at"] for entry in unit.history if entry.get("state") == "merged"]
    return bool(stamps) and now - datetime.fromisoformat(stamps[-1]) <= timedelta(days=HORIZON_DAYS)
