"""The ordering `test_stopping_still_awaits_the_builds_in_flight` must rule out: a slot
frees before the refusal is written.

A freed slot is refilled at once, so a refusal landing after another unit finished does not
stop the unit already started. The ordering is held by events, not by timing."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit.pipeline import pause
from agent_build_kit.pipeline.units import IN_REVIEW
from tests.cli.test_tick_scheduling import WAIT
from tests.tick_pass import Builder, install_builder, isolate, stored, tick, workspace
from tests.waiting import wait_for

pytestmark = pytest.mark.usefixtures("scripted_engine")


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    isolate(monkeypatch)


@pytest.fixture
def builder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Builder:
    return install_builder(tmp_path, monkeypatch)


def test_a_refusal_after_a_slot_freed_does_not_unstart_the_next_unit(
    builder: Builder, tmp_path: Path
) -> None:
    inst = workspace(tmp_path, max_concurrent=3)
    builder.store.upsert(
        [
            stored("quick/1"),
            stored("slow/1", repo="platform"),
            stored("stops/1"),
            stored("later/1"),
        ]
    )

    def refused() -> None:
        # The refusal comes only once quick/1's freed slot has started later/1.
        wait_for(lambda: "later/1" in builder.started, what="later/1 to start", timeout=WAIT)
        pause.pause_until(
            datetime.now(UTC) + timedelta(hours=1),
            reason="the model refused",
            marker=tmp_path / "paused.json",
            kind="rate_limit",
        )

    builder.scripts["stops/1"] = refused
    builder.scripts["slow/1"] = lambda: wait_for(
        (tmp_path / "paused.json").exists, what="the pause file", timeout=WAIT
    )

    assert tick(inst) == 0

    assert sorted(builder.started) == ["later/1", "quick/1", "slow/1", "stops/1"]
    assert builder.store.get("slow/1").state == IN_REVIEW
    assert builder.store.get("later/1").state == IN_REVIEW
