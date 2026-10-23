"""`recorded_history` reads a class's track record from the verdict file, and gives none when the
file cannot be read."""

from __future__ import annotations

import json
from pathlib import Path

from agent_build_kit.pipeline.verdict import NO_HISTORY, ClassHistory
from agent_build_kit.pipeline.verdict_record import recorded_history


def record(unit_class: str, outcome: str) -> dict[str, object]:
    return {
        "final": True,
        "unit_class": unit_class,
        "brief": True,
        "outcome": outcome,
        "evidence_tier": "auto",
    }


def test_a_missing_file_gives_no_history(tmp_path: Path) -> None:
    assert recorded_history(tmp_path / "verdicts.json", "app/unit-test") == NO_HISTORY


def test_a_malformed_file_gives_no_history(tmp_path: Path) -> None:
    path = tmp_path / "verdicts.json"
    path.write_text("{not json")
    assert recorded_history(path, "app/unit-test") == NO_HISTORY

    path.write_text(json.dumps({"u": 3}))
    assert recorded_history(path, "app/unit-test") == NO_HISTORY


def test_a_real_file_gives_the_classs_samples_and_clean_count(tmp_path: Path) -> None:
    path = tmp_path / "verdicts.json"
    path.write_text(
        json.dumps(
            {
                "a": record("app/unit-test", "clean"),
                "b": record("app/unit-test", "reverted"),
                "c": record("app/e2e-test", "clean"),
            }
        )
    )

    assert recorded_history(path, "app/unit-test") == ClassHistory(samples=2, clean=1)
