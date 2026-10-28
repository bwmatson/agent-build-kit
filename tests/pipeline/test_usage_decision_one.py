# ruff: noqa: F811 — the imported fixture is requested by name
"""Starting a unit and the gate before its first agent step ask one question (spec:
usage-pause-slots, starting a unit and the gate ask one question).

The guard is the real one on a usage payload kept in the state directory, with a history of
`auto` and `full` units laid beside it, so a `full` unit is forecast at more points than an
`auto` one. A round is `run_round`; the gate's answer is `ask`, the way a gate asks it.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.admission_record import (
    ADMISSIONS_NAME,
    AdmissionRecord,
    read_admissions,
)
from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.verdict import ReviewTier
from agent_build_kit.pipeline.vocabulary import WaitReason
from tests.cli.test_admission_asks_own_account import isolated, round_of, unit, waits  # noqa: F401
from tests.conftest import make_installation
from tests.usage_forecast_fixtures import spec_history
from tests.usage_forecast_gate import EXACT, ask, keep_points, lay
from tests.usage_host import Host, payload

MINUTE = timedelta(minutes=1)
MARGIN = 5
THRESHOLD = 80


def tiered(uid: str, tier: ReviewTier) -> StoredUnit:
    """A ready unit of `app` of review tier `tier`, ten lines long as the gate's ask says."""
    return unit(uid, "app").model_copy(update={"review_tier": tier.value, "estimated_lines": 10})


def workspace(tmp_path: Path, host: Host, units: list[StoredUnit], *, session: float):
    """`units` in a store beside the usage cache, a history, and a reading of `session`%."""
    inst = make_installation(
        tmp_path / "planning",
        planning={"state_dir": ".", "worktree_root": str(tmp_path / "trees")},
        repos={"app": {"path": str(tmp_path / "app"), "slug": "example/app"}},
        runtimes={
            "claude_code": {
                "limits": {
                    "session": {"usage_pause_pct": THRESHOLD},
                    "weekly": {"usage_pause_pct": THRESHOLD},
                    **EXACT,
                }
            }
        },
    )
    inst.state_dir.mkdir(parents=True, exist_ok=True)
    host.keep_in(inst.state_dir)
    lay(host, spec_history())
    keep_points(host)
    host.keep_reading(MINUTE, payload(session=session, weekly=6.0))
    store = UnitStore(inst.state_dir / "units.json")
    store.upsert(units)
    return inst, store


def record_of(inst: Installation, uid: str) -> AdmissionRecord:
    records = read_admissions(inst.state_dir / ADMISSIONS_NAME)
    return next(each for each in records if each.unit == uid)


def test_a_reading_under_the_threshold_with_a_forecast_over_it_refuses_as_the_gate_would(
    tmp_path: Path, host: Host
) -> None:
    """70% is under 80, and a `full` unit's forecast and the margin take it past 80. An `auto`
    unit beside it must not set the forecast the `full` one is judged on."""
    inst, store = workspace(
        tmp_path,
        host,
        [tiered("one/1", ReviewTier.AUTO), tiered("two/1", ReviewTier.FULL)],
        session=70.0,
    )

    started = round_of(inst, store)
    gate = ask(ReviewTier.FULL, "two/1")

    assert not gate.may_start
    assert started == ["one/1"]
    wait = waits(inst)["two/1"]
    assert wait.reason is WaitReason.USAGE_PAUSE
    assert gate.reason in wait.detail
    assert record_of(inst, "two/1").usage.reason == gate.reason


def test_a_reading_with_room_admits_and_the_gate_then_passes(tmp_path: Path, host: Host) -> None:
    inst, store = workspace(
        tmp_path,
        host,
        [tiered("one/1", ReviewTier.AUTO), tiered("two/1", ReviewTier.FULL)],
        session=40.0,
    )

    started = round_of(inst, store)
    gate = ask(ReviewTier.FULL, "two/1")

    assert started == ["one/1", "two/1"]
    assert gate.may_start
    usage = record_of(inst, "two/1").usage
    assert usage.may_start is True
    assert usage.reason == gate.reason


@pytest.mark.parametrize("session", [40.0, 70.0])
def test_the_admission_record_carries_the_reading_the_forecast_the_margin_and_the_threshold(
    tmp_path: Path, host: Host, session: float
) -> None:
    inst, store = workspace(tmp_path, host, [tiered("two/1", ReviewTier.FULL)], session=session)

    round_of(inst, store)
    gate = ask(ReviewTier.FULL, "two/1")

    usage = record_of(inst, "two/1").usage
    assert usage.source
    assert usage.age_seconds is not None
    assert usage.threshold == THRESHOLD
    assert usage.margin == MARGIN
    assert usage.forecast is not None
    assert usage.forecast > 0
    assert usage.forecast == pytest.approx(gate.forecast)
    assert (gate.threshold, gate.margin) == (THRESHOLD, MARGIN)
