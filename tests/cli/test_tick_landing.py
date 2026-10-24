"""The tick runs the landing step after the poll, only when review and a listed class allow it
(spec: auto-land). The tick is the real one with its edges faked, over a stand-in forge."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.units import IN_REVIEW, MERGED
from tests.factories import new_unit
from tests.forges.stand_in import StandInForge
from tests.landing_support import apply_review, listed_review, make_landable
from tests.tick_driver import Setup, make_setup

pytestmark = pytest.mark.usefixtures("scripted_engine")

FIRST = "first/1"
SECOND = "second/1"


class Tick:
    """Two units in review that may land, a forge to land them on, and the order of the poll
    and the landing step."""

    def __init__(self, setup: Setup, patch: pytest.MonkeyPatch) -> None:
        self.setup, self.store = setup, setup.store
        self.forge = StandInForge()
        self.order: list[str] = []
        self.entered = 0
        patch.setattr(setup.inst, "forge_of", lambda repo: (self.forge, self.forge.repo_id()))
        patch.setattr(cli, "poll_all", lambda inst, **kwargs: self.order.append("poll"))
        real_land = cli.land_units

        def land(*args: Any, **kwargs: Any) -> None:
            self.order.append("land")
            self.entered += 1
            real_land(*args, **kwargs)

        patch.setattr(cli, "land_units", land)
        self.store.upsert([new_unit(FIRST), new_unit(SECOND)])
        self.store.set_state(FIRST, IN_REVIEW, pr=1, branch=f"spec/{FIRST}")
        self.store.set_state(SECOND, IN_REVIEW, pr=2, branch=f"spec/{SECOND}")
        make_landable(setup.inst, self.store, self.forge, {FIRST: 1, SECOND: 2})


@pytest.fixture
def tick(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Tick:
    return Tick(make_setup(tmp_path, monkeypatch), monkeypatch)


def test_a_pass_with_review_enabled_and_a_class_listed_lands_after_the_poll(tick: Tick) -> None:
    apply_review(tick.setup.inst, listed_review())

    tick.setup.tick()

    assert tick.order.index("poll") < tick.order.index("land")
    assert sorted(pr for pr, head in tick.forge.merge_calls) == [1, 2]


def test_a_pass_with_the_list_empty_never_calls_the_forge_s_merge(tick: Tick) -> None:
    apply_review(tick.setup.inst, listed_review(listed=()))

    tick.setup.tick()

    assert tick.entered == 1, "the step is entered, and merges nothing"
    assert tick.forge.merge_calls == []


def test_an_error_landing_one_unit_is_logged_and_the_others_are_still_tried(
    tick: Tick, capsys: pytest.CaptureFixture[str]
) -> None:
    apply_review(tick.setup.inst, listed_review())
    tick.forge.merge_failures = [RuntimeError("the host fell over")]

    tick.setup.tick()

    assert len(tick.forge.merge_calls) == 2, "the unit after the one that failed was tried"
    assert "the host fell over" in capsys.readouterr().out
    states = {unit: tick.store.get(unit).state for unit in (FIRST, SECOND)}
    assert sorted(states.values()) == [IN_REVIEW, MERGED]
