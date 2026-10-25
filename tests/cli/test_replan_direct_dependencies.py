"""A replan prints what changed among the direct dependencies, and nothing for a redundant one.

A unit stored with a dependency its other dependency reaches is stored reduced by the replan
(`abk replan` reduces the store before it plans), so the reduction itself is never reported as
a change of the unit.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.cli.replan_driver import Replan, answer, planned, tasks_md
from tests.factories import stored_unit as unit

pytestmark = pytest.mark.usefixtures("scripted_engine")

LINES = 80


def stored(n: int, *depends: str):
    return unit(
        f"feature/{n}", change="feature", groups=(n,), depends_on=depends, estimated_lines=LINES
    )


def run_replan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Replan:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(4))
    # A store from before dependencies were reduced: feature/3 lists feature/1 and the
    # feature/2 that is built on it.
    run.store.import_units(
        [
            stored(1),
            stored(2, "feature/1"),
            stored(3, "feature/1", "feature/2"),
            stored(4, "feature/1"),
        ]
    )
    return run


def plan() -> str:
    return answer(
        planned("feature/1", (1,)),
        planned("feature/2", (2,), depends_on=("feature/1",)),
        planned("feature/3", (3,), depends_on=("feature/1", "feature/2")),
        planned("feature/4", (4,), depends_on=("feature/2",)),
    )


def lines_about(out: str, uid: str) -> list[str]:
    """The lines about `uid`'s dependencies; a change of review tier is not one."""
    return [
        line
        for line in out.splitlines()
        if line.startswith(f"{uid}:") and "review tier" not in line
    ]


def test_a_replan_prints_the_direct_changes_and_nothing_for_a_redundant_dependency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = run_replan(tmp_path, monkeypatch)

    code, out = run.run(capsys, "feature", reply=plan())

    assert code == 0
    assert run.store.get("feature/3").depends_on == ("feature/2",)
    assert lines_about(out, "feature/3") == []
    assert lines_about(out, "feature/4") == [
        "feature/4: no longer depends on feature/1",
        "feature/4: now depends on feature/2",
    ]

    # A replan after the reduction has nothing to say about a unit that did not change.
    code, out = run.run(capsys, "feature", reply=plan())

    assert code == 0
    for n in (1, 2, 3, 4):
        assert lines_about(out, f"feature/{n}") == []
