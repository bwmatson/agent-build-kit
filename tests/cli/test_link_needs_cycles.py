"""A `Needs:` line that would close a cycle is refused, and what is stored is left alone
(spec: unit-scheduling). The lines go through `link_needs`, as every tick applies them."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.cycles import CycleEdge
from tests.cli.replan_driver import OPT_OUT, Replan, tasks_md
from tests.factories import unit

CYCLE = ("zbase/1", "c-top/1", "a-left/1", "zbase/1")


def needs_md(*lines: str) -> str:
    text = f"# Tasks\n\n{OPT_OUT}\n## 1. [app] [tier1] The work\n\n"
    text += "".join(f"Needs: {line} — a reason\n" for line in lines)
    return text + "\n- [ ] 1.1 Test: it.\n- [ ] 1.2 Do it.\n"


def diamond_closed_by_its_base(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Replan:
    """A diamond `c-top` -> `a-left`, `b-right` -> `zbase`, linked in name order, then
    `zbase` needing `c-top` (which closes it) and `extra` (which does not)."""
    run = Replan(
        tmp_path,
        monkeypatch,
        **{
            "a-left": needs_md("zbase group 1"),
            "b-right": needs_md("zbase group 1"),
            "c-top": needs_md("a-left group 1", "b-right group 1"),
            "extra": tasks_md(1),
            "zbase": needs_md("c-top group 1", "extra group 1"),
        },
    )
    run.store.upsert(
        [
            unit(f"{change}/1", change=change, groups=(1,))
            for change in ("a-left", "b-right", "c-top", "extra", "zbase")
        ]
    )
    return run


def test_a_needs_that_closes_a_cycle_is_refused_and_the_rest_of_the_graph_is_linked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = diamond_closed_by_its_base(tmp_path, monkeypatch)

    refused = cli.link_needs(run.inst, store=run.store)

    assert refused == [CycleEdge(unit="zbase/1", dependency="c-top/1", cycle=CYCLE)]
    depends = {u.id: u.depends_on for u in run.store.all()}
    assert depends["a-left/1"] == ("zbase/1",)
    assert depends["b-right/1"] == ("zbase/1",)
    assert depends["c-top/1"] == ("a-left/1", "b-right/1")
    assert depends["zbase/1"] == ("extra/1",), "the other Needs: of the unit is still linked"
    lines = [line for line in capsys.readouterr().out.splitlines() if " -> ".join(CYCLE) in line]
    assert len(lines) == 1


def test_a_refused_needs_is_logged_once_in_each_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = diamond_closed_by_its_base(tmp_path, monkeypatch)

    cli.link_needs(run.inst, store=run.store)
    cli.link_needs(run.inst, store=run.store)

    lines = [line for line in capsys.readouterr().out.splitlines() if " -> ".join(CYCLE) in line]
    assert len(lines) == 2


def test_a_cycle_already_stored_is_left_alone_and_a_needs_closing_a_longer_one_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `one` -> `two` and `two` -> `three` are stored (a planner edge, a linked Needs:);
    # `three` needing `one` completes a cycle over three changes. `old-a` and `old-b`
    # are a cycle an older version stored, both lines declared.
    run = Replan(
        tmp_path,
        monkeypatch,
        one=tasks_md(1),
        two=tasks_md(1),
        three=needs_md("one group 1"),
        **{"old-a": needs_md("old-b group 1"), "old-b": needs_md("old-a group 1")},
    )
    run.store.upsert(
        [
            unit("one/1", change="one", groups=(1,), depends_on=("two/1",)),
            unit("two/1", change="two", groups=(1,), depends_on=("three/1",)),
            unit("three/1", change="three", groups=(1,)),
            unit("old-a/1", change="old-a", groups=(1,), depends_on=("old-b/1",)),
            unit("old-b/1", change="old-b", groups=(1,), depends_on=("old-a/1",)),
        ]
    )

    refused = cli.link_needs(run.inst, store=run.store)

    assert [(r.unit, r.dependency) for r in refused] == [("three/1", "one/1")]
    assert refused[0].cycle == ("three/1", "one/1", "two/1", "three/1")
    depends = {u.id: u.depends_on for u in run.store.all()}
    assert depends["three/1"] == ()
    assert depends["old-a/1"] == ("old-b/1",)
    assert depends["old-b/1"] == ("old-a/1",)
