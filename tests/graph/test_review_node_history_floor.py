"""The review node passes the class's recorded history into the verdict, so the history floor
reads the verdict records of earlier units (spec: units-are-triaged-by-review-tier)."""

from __future__ import annotations

import json
from pathlib import Path

from agent_build_kit.pipeline.verdict_record import VERDICTS
from tests.conftest import make_installation
from tests.factories import unit
from tests.graph.test_build_path import build
from tests.graph.test_remaining_paths import fresh

UNIT_ID = unit().id
UNIT_CLASS = "app/unit-test"
MIN_SAMPLES = 3
APPROVED_AUTO = json.dumps({"approved": True, "feedback": "", "classification": "auto"})


def final_entry(tmp_path: Path, *, earlier: int) -> dict[str, object]:
    """The approving round's entry, with `earlier` clean records of the unit's class on file."""
    make_installation(
        tmp_path,
        review={"enabled": True, "auto_land": {"min_samples": MIN_SAMPLES}},
    )
    (tmp_path / VERDICTS).write_text(
        json.dumps(
            {
                f"earlier-{n}": {
                    "final": True,
                    "unit_class": UNIT_CLASS,
                    "brief": True,
                    "outcome": "clean",
                    "evidence_tier": "auto",
                }
                for n in range(earlier)
            }
        )
    )
    recorder = fresh(tmp_path, tier="unit-test")
    recorder.verdicts = [APPROVED_AUTO]
    build(tmp_path, recorder)
    entry = json.loads((tmp_path / VERDICTS).read_text())[UNIT_ID]
    assert entry["final"] is True
    assert entry["unit_class"] == UNIT_CLASS
    return entry


def test_a_class_with_enough_clean_history_is_not_held_by_the_floor(tmp_path: Path) -> None:
    entry = final_entry(tmp_path, earlier=MIN_SAMPLES)

    assert (entry["tier"], entry["evidence_tier"]) == ("auto", "auto")


def test_a_class_short_of_samples_is_held_at_light_naming_the_shortfall(tmp_path: Path) -> None:
    entry = final_entry(tmp_path, earlier=MIN_SAMPLES - 1)

    assert entry["tier"] == "light"
    assert entry["evidence_tier"] == "auto"
    assert f"{MIN_SAMPLES - 1} samples" in str(entry["reason"])
