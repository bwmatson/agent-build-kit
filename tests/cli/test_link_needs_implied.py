"""A `Needs:` line the chain already implies is not linked again, and `needs` names
every declared target (spec: unit-scheduling). The lines go through `link_needs`, as
every tick applies them."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.cycles import CycleEdge
from agent_build_kit.pipeline.unit_store import UnitStore
from tests.cli.replan_driver import Replan, needs_md, tasks_md
from tests.factories import unit

ROUNDS = 10


def spy_writes(run: Replan, monkeypatch: pytest.MonkeyPatch) -> dict[str, list[tuple]]:
    """Every call to the store's two dependency writers, recorded and then made."""
    calls: dict[str, list[tuple]] = {"set_dependencies": [], "set_needs": []}
    for name in calls:
        real = getattr(UnitStore, name)

        def spy(*args, _name=name, _real=real):
            calls[_name].append(args)
            return _real(run.store, *args)

        monkeypatch.setattr(run.store, name, spy)
    return calls


def chain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *targets: str) -> Replan:
    """`feature` depends on `parent`, which depends on `root`, and has a `Needs:` line
    for each change in `targets`; `extra` is independent and `loop` depends on `feature`."""
    run = Replan(
        tmp_path,
        monkeypatch,
        root=tasks_md(1),
        parent=tasks_md(1),
        feature=needs_md(*(f"{target} group 1" for target in targets)),
        extra=tasks_md(1),
        loop=tasks_md(1),
    )
    run.store.upsert(
        [
            unit("root/1", change="root", groups=(1,)),
            unit("parent/1", change="parent", groups=(1,), depends_on=("root/1",)),
            unit("feature/1", change="feature", groups=(1,), depends_on=("parent/1",)),
            unit("extra/1", change="extra", groups=(1,)),
            unit("loop/1", change="loop", groups=(1,), depends_on=("feature/1",)),
        ]
    )
    return run


def test_a_target_the_chain_implies_is_never_linked_and_is_named_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = chain(tmp_path, monkeypatch, "root")
    calls = spy_writes(run, monkeypatch)

    for round_ in range(ROUNDS):
        cli.link_needs(run.inst, store=run.store)
        feature = run.store.get("feature/1")
        assert feature.depends_on == ("parent/1",), f"round {round_}"
        if round_ == 0:
            assert feature.needs == ("root/1",)

    assert len(calls["set_needs"]) == 1, "needs is written once, not every round"
    assert calls["set_dependencies"] == []
    assert "now depends on" not in capsys.readouterr().out


def test_a_target_not_reached_is_added_once_beside_one_that_is_implied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = chain(tmp_path, monkeypatch, "root", "extra")

    cli.link_needs(run.inst, store=run.store)
    cli.link_needs(run.inst, store=run.store)

    feature = run.store.get("feature/1")
    assert feature.depends_on == ("parent/1", "extra/1")
    assert set(feature.needs) == {"root/1", "extra/1"}
    lines = [line for line in capsys.readouterr().out.splitlines() if "now depends on" in line]
    assert len(lines) == 1
    assert "extra/1" in lines[0]


def test_a_target_that_reaches_a_listed_dependency_is_stored_without_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `feature` lists `root` and the line names `parent`, which depends on `root`.
    run = chain(tmp_path, monkeypatch, "parent")
    run.store.set_dependencies("feature/1", ("root/1",))

    cli.link_needs(run.inst, store=run.store)

    feature = run.store.get("feature/1")
    assert feature.depends_on == ("parent/1",)
    assert feature.needs == ("parent/1",)


def test_removing_the_line_removes_the_target_from_needs_and_keeps_the_dependencies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = chain(tmp_path, monkeypatch, "root", "extra")
    cli.link_needs(run.inst, store=run.store)
    assert set(run.store.get("feature/1").needs) == {"root/1", "extra/1"}

    run.write("feature", needs_md("extra group 1"))
    cli.link_needs(run.inst, store=run.store)
    assert run.store.get("feature/1").needs == ("extra/1",)

    run.write("feature", needs_md())
    cli.link_needs(run.inst, store=run.store)
    feature = run.store.get("feature/1")
    assert feature.needs == ()
    assert feature.depends_on == ("parent/1", "extra/1")


def test_a_target_that_depends_on_the_unit_is_refused_once_beside_an_implied_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # `loop` depends on `feature`, so `feature` needing `loop` would close a cycle.
    run = chain(tmp_path, monkeypatch, "root", "loop")

    refused = cli.link_needs(run.inst, store=run.store)

    cycle = ("feature/1", "loop/1", "feature/1")
    assert refused == [CycleEdge(unit="feature/1", dependency="loop/1", cycle=cycle)]
    feature = run.store.get("feature/1")
    assert feature.depends_on == ("parent/1",)
    assert feature.needs == ("root/1",)
    lines = [line for line in capsys.readouterr().out.splitlines() if " -> ".join(cycle) in line]
    assert len(lines) == 1
