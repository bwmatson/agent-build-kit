"""What the planner-prompt tests of per-tier sizing share: the prompt a round sends, as the
planner's runtime receives it, over units that merged at a known ratio."""

from __future__ import annotations

from agent_build_kit.config import active
from agent_build_kit.pipeline.planner import plan_round
from agent_build_kit.pipeline.unit_size import Calibration, Kind, calibrations, recent_examples
from agent_build_kit.pipeline.unit_store import StoredUnit
from tests.calibration_support import sample

APP = Kind(repo="app", tier="unit-test")


def landed_at_one_and_a_half() -> list[StoredUnit]:
    """Twenty merged `app` units that each landed at 1.5 times their estimate."""
    return [sample(0, at=at, estimate=400, actual=600) for at in range(20)]


def prompt_for(units: list[StoredUnit]) -> str:
    """The prompt a round sends, with the ratios and examples a caller computes from `units`."""
    found = calibrations(units)
    n = active().global_limits.calibration_examples
    captured: dict[str, str] = {}

    def answer(prompt: str) -> str:
        captured["prompt"] = prompt
        return '{"units": []}'

    plan_round(
        changes={"c": "## 1. [app] [unit-test] x\n"},
        in_flight=[],
        calibrations=found,
        examples={kind: recent_examples(units, kind, n) for kind in found},
        run_claude=answer,
    )
    return captured["prompt"]


def ratio_of(units: list[StoredUnit]) -> Calibration:
    return calibrations(units)[APP]
