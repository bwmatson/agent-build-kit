"""A verdict recorded while the demotion file cannot be read is held at `light`, so a broken
file never lifts a demotion by being unread (spec: class-demotion, only a person lifts one)."""

from __future__ import annotations

import json
from pathlib import Path

from agent_build_kit.pipeline.demotion_record import DEMOTIONS
from agent_build_kit.pipeline.verdict_record import VERDICTS
from tests.conftest import make_installation
from tests.factories import unit
from tests.graph.test_build_path import build
from tests.graph.test_remaining_paths import fresh

UNIT_ID = unit().id
UNIT_CLASS = "app/unit-test"
APPROVED_AUTO = json.dumps({"approved": True, "feedback": "", "classification": "auto"})


def final_entry(tmp_path: Path, demotions: str | None) -> dict[str, object]:
    make_installation(tmp_path, review={"enabled": True, "auto_land": {"min_samples": 1}})
    earlier = {
        "final": True,
        "unit_class": UNIT_CLASS,
        "brief": True,
        "outcome": "clean",
        "evidence_tier": "auto",
    }
    (tmp_path / VERDICTS).write_text(json.dumps({"earlier": earlier}))
    if demotions is not None:
        (tmp_path / DEMOTIONS).write_text(demotions)
    recorder = fresh(tmp_path, tier="unit-test")
    recorder.verdicts = [APPROVED_AUTO]
    build(tmp_path, recorder)
    return json.loads((tmp_path / VERDICTS).read_text())[UNIT_ID]


def test_an_unreadable_demotion_file_holds_the_verdict_at_light_naming_the_file(
    tmp_path: Path,
) -> None:
    entry = final_entry(tmp_path, "not json")

    assert (entry["tier"], entry["evidence_tier"]) == ("light", "auto")
    assert "demotion file cannot be read" in str(entry["reason"])


def test_a_malformed_standing_record_holds_the_verdict_at_light(tmp_path: Path) -> None:
    broken = json.dumps({UNIT_CLASS: {"lifted": None, "triggers": []}})

    assert final_entry(tmp_path, broken)["tier"] == "light"


def test_no_demotion_file_leaves_the_verdict_at_auto(tmp_path: Path) -> None:
    assert final_entry(tmp_path, None)["tier"] == "auto"
