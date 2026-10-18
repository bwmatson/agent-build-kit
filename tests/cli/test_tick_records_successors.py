"""The first tick after a unit was replaced without a record gives it its successor, repoints the
units that name it in the same tick, and is silent on the next (spec:
a-replaced-unit-points-to-its-successor)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.units import IN_REVIEW, UnitState
from tests.tick_pass import (
    Builder,
    install_builder,
    isolate,
    stored,
    tick,
    warm_unit_graphs,
    workspace,
)

pytestmark = pytest.mark.usefixtures("scripted_engine")


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    warm_unit_graphs(tmp_path)
    isolate(monkeypatch)


@pytest.fixture
def builder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Builder:
    return install_builder(tmp_path, monkeypatch)


def test_a_tick_records_the_successor_repoints_both_edges_and_is_silent_the_next_time(
    builder: Builder, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = workspace(tmp_path)
    builder.store.import_units(
        [
            stored("x/3", groups=(3,), state=UnitState.UNPLANNED),
            stored("x/12", groups=(3,), state=IN_REVIEW, pr=12, branch="spec/x/12"),
            *(
                stored(
                    uid,
                    groups=(1,),
                    depends_on=("x/3",),
                    state=IN_REVIEW,
                    pr=n,
                    branch=f"spec/{uid}",
                )
                for n, uid in ((1, "a/1"), (2, "b/1"))
            ),
        ]
    )

    assert tick(inst) == 0

    out = capsys.readouterr().out
    assert builder.store.get("x/3").superseded_by == ("x/12",)
    assert [builder.store.get(uid).depends_on for uid in ("a/1", "b/1")] == [("x/12",)] * 2
    assert out.count("successors recorded: 1 unit(s)") == 1
    assert "a/1: dependency x/3 is now x/12 (replaced by a replan)" in out
    assert "b/1: dependency x/3 is now x/12 (replaced by a replan)" in out
    assert out.index("successors recorded") < out.index("dependency x/3 is now")

    assert tick(inst) == 0

    again = capsys.readouterr().out
    assert "successors recorded" not in again
    assert "is now x/12" not in again
