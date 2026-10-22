"""A verdicts file holding a recorded verdict of a given tier for each named unit."""

import json
from collections.abc import Mapping
from pathlib import Path

from agent_build_kit.pipeline.verdict import ReviewTier
from agent_build_kit.pipeline.verdict_record import VerdictEntry


def write_verdicts(path: Path, tiers: Mapping[str, ReviewTier]) -> None:
    """Write `path` as the verdicts file with one final verdict per unit id, of its tier."""
    recorded = {}
    for unit, tier in tiers.items():
        entry = VerdictEntry(
            unit=unit,
            change=unit.split("/")[0],
            round=1,
            final=True,
            unit_class="app/unit-test",
            planned_estimate=None,
            classification=tier,
            drivers=(),
            evidence_tier=tier,
            tier=tier,
            reason="because",
            paths=(),
            lines=3,
            brief=True,
        )
        recorded[unit] = entry.model_dump(mode="json", exclude={"split"})
    path.write_text(json.dumps(recorded))
