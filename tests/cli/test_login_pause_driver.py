"""A login pause at the gate, seen through a whole tick (spec: login-pause): it pauses the unit
and nothing else: no pause of the whole account for usage and no usage metric."""

from __future__ import annotations

import pytest

from agent_build_kit.pipeline.unit_store import Cause
from tests.cli.test_login_pause import LINE
from tests.cli.test_metric_emit_sites import (  # noqa: F401 — fixtures
    Emitted,
    emitted,
    exported,
    named,
)
from tests.cli.test_tick_telemetry import UNIT, Ticks, ticks  # noqa: F401 — fixture
from tests.time_limit import LOADED_TEST_TIME_LIMIT

# The tests of this module run whole passes through the `ticks` fixture, whose time depends on
# the machine's load.
pytestmark = pytest.mark.time_limit(LOADED_TEST_TIME_LIMIT)


def test_a_login_pause_writes_no_usage_pause_of_the_account_and_counts_no_usage_pause(
    ticks: Ticks,  # noqa: F811
    emitted: list[Emitted],  # noqa: F811
) -> None:
    ticks.options["login_rejected"] = lambda: LINE

    ticks.tick()

    stored = ticks.store.get(UNIT)
    assert stored.cause is Cause.LOGIN
    assert list(ticks.inst.state_dir.glob("paused*.json")) == []
    assert named(emitted, "abk.usage.pauses") == []
