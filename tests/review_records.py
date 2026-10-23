"""Verdict records with an outcome, for the tests of what reports on them."""

from __future__ import annotations

import json
from pathlib import Path


def record(outcome: str, *, unit_class: str, brief: bool = True, evidence: str = "light") -> dict:
    return {
        "final": True,
        "unit_class": unit_class,
        "brief": brief,
        "outcome": outcome,
        "evidence_tier": evidence,
    }


def sample_records() -> dict[str, dict]:
    """With three samples at 0.9 as the gates: `docs` clears them (two of its samples had
    evidence tier `auto`, and two more records lack the brief); `code` does not;
    `app/unit-test` clears but no `review.classes` entry names it."""
    records = [
        *[record("clean", unit_class="docs", evidence="auto")] * 2,
        record("clean", unit_class="docs"),
        *[record("clean", unit_class="docs", brief=False)] * 2,
        record("clean", unit_class="code"),
        record("reworked", unit_class="code"),
        *[record("clean", unit_class="app/unit-test")] * 3,
    ]
    return {"feature/" + str(n): r for n, r in enumerate(records, start=1)}


def write_records(path: Path, records: dict[str, dict]) -> None:
    path.write_text(json.dumps(records))
