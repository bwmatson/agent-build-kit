"""A round decides whether to resume a paused unit by the question its own gate will ask: its
review tier and size, not the lowest tier the round could start (spec: usage-pause-slots, a
paused unit is not resumed early). The guard is the real one, on a usage payload kept in the
state directory, as in the starting-a-unit tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit.pipeline.verdict import ReviewTier
from tests.cli.test_admission_asks_own_account import isolated, round_of  # noqa: F401
from tests.cli.usage_pause_support import pause_for_usage, with_threads
from tests.pipeline.test_usage_decision_one import tiered, workspace
from tests.usage_host import Host

AUTO = "auto/1"
FULL = "full/1"


@pytest.mark.parametrize(
    ("session", "resumed"),
    [(67.0, False), (40.0, True)],
    ids=["forecast-over-threshold", "forecast-fits"],
)
def test_a_paused_unit_is_resumed_only_when_its_own_step_fits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    host: Host,
    session: float,
    resumed: bool,
) -> None:
    """At 67% the `auto` unit's forecast fits under the threshold and the `full` unit's does
    not: the `auto` ask allowing is no reason to resume the `full` unit, which its gate would
    refuse again."""
    inst, store = workspace(
        tmp_path,
        host,
        [tiered(AUTO, ReviewTier.AUTO), tiered(FULL, ReviewTier.FULL)],
        session=session,
    )
    pause_for_usage(store, FULL, datetime.now(UTC) + timedelta(hours=3))
    with_threads(monkeypatch, FULL)

    started = round_of(inst, store)

    assert AUTO in started
    assert (FULL in started) is resumed
