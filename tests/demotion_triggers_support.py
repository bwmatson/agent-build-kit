"""Builders for the tests of the demotion triggers: units, verdict records and the policy."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from agent_build_kit.config import AutoLandConfig, DemotionConfig, ReviewConfig
from agent_build_kit.pipeline import demotion_record
from agent_build_kit.pipeline.demotion_triggers import evaluate_demotions
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import UnitState
from tests.factories import stored_unit

START = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
NOW = datetime(2026, 2, 1, 9, 0, tzinfo=UTC)


def policy(*, listed: tuple[str, ...] = ("docs",)) -> ReviewConfig:
    """Review with a window of 10, a minimum agreement of 0.9 and the default minimum samples."""
    return ReviewConfig(
        classes={"docs": ["docs/**"], "code": ["src/**"]},
        auto_land=AutoLandConfig(classes=list(listed)),
        demotion=DemotionConfig(window=10, min_agreement=0.9),
    )


def merged_unit(
    uid: str,
    *,
    day: int = 0,
    auto: bool = False,
    change: str = "feature",
    pr: int | None = None,
) -> StoredUnit:
    """A merged unit of `change`, merged `day` days after `START`; landed by the pipeline when
    `auto`."""
    entry: dict[str, Any] = {"state": "merged", "at": (START + timedelta(days=day)).isoformat()}
    if auto:
        entry["cause"] = "auto_landed"
    return stored_unit(uid, change=change, state=UnitState.MERGED, pr=pr, history=(entry,))


def record(
    outcome: str,
    *,
    unit_class: str = "docs",
    auto: bool = False,
    brief: bool = True,
) -> dict[str, Any]:
    """A final verdict record whose outcome the sweep has derived."""
    return {
        "final": True,
        "unit_class": unit_class,
        "brief": brief,
        "outcome": outcome,
        "evidence_tier": "auto",
        "auto_landed": auto,
    }


def samples(*outcomes: str, brief: bool = True) -> tuple[list[StoredUnit], dict[str, Any]]:
    """One person-merged unit and record for each outcome, merged a day apart in this order."""
    units = [merged_unit(f"feature/{n}", day=n) for n, _ in enumerate(outcomes, start=1)]
    records = {u.id: record(o, brief=brief) for u, o in zip(units, outcomes, strict=True)}
    return units, records


def evaluate(
    tmp_path: Path,
    units: list[StoredUnit],
    records: dict[str, Any],
    *,
    review: ReviewConfig | None = None,
    said: list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Write `records`, evaluate the demotions and read what is demoted."""
    verdicts = tmp_path / "verdicts.json"
    verdicts.write_text(json.dumps(records))
    demotions = tmp_path / demotion_record.DEMOTIONS
    evaluate_demotions(
        units,
        verdicts=verdicts,
        audits=tmp_path / "audits.json",
        demotions=demotions,
        review=review or policy(),
        at=NOW,
        log=(said if said is not None else []).append,
    )
    return demotion_record.read_demotions(demotions)
