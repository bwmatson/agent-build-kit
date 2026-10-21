"""A join accepts a unit-test with an integration-test and never an e2e-test with another kind;
the unit that survives a join takes the widest kind."""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest

from agent_build_kit.pipeline.joins import JoinContext, JoinRefused, check_joins
from agent_build_kit.pipeline.units import Join
from agent_build_kit.pipeline.work_graph import TaskGroup
from tests.cli.replan_driver import Replan, answer, planned, tagged_md
from tests.factories import ordinary_floor, stored_unit

UNIT, INTEGRATION, E2E = "unit-test", "integration-test", "e2e-test"
PAIRS = list(itertools.permutations((UNIT, INTEGRATION, E2E), 2))
ALLOWED = [(a, b) for a, b in PAIRS if E2E not in (a, b)]
REFUSED = [(a, b) for a, b in PAIRS if E2E in (a, b) and INTEGRATION in (a, b)]


def tagged(kind: str) -> TaskGroup:
    return TaskGroup(number=1, repo="app", tier=kind, title="A group", line=3, task_count=2)


def check_group(group_kind: str, onto_kind: str) -> None:
    onto = stored_unit("base/1", change="base", tier=onto_kind)
    check_joins(
        [Join(onto="base/1", change="feature", groups=(1,), estimated_lines=100)],
        context=JoinContext(stored=(onto,), catalog={"base": (tagged(onto_kind),)}),
        plan=[],
        change="feature",
        groups=[tagged(group_kind)],
        built=set(),
        ceiling=750,
        floor=ordinary_floor,
    )


def check_unit(taken_kind: str, onto_kind: str) -> None:
    onto = stored_unit("base/1", change="base", tier=onto_kind)
    taken = stored_unit("later/1", change="later", tier=taken_kind, depends_on=("base/1",))
    check_joins(
        [Join(onto="base/1", unit="later/1")],
        context=JoinContext(
            stored=(onto, taken),
            catalog={"base": (tagged(onto_kind),), "later": (tagged(taken_kind),)},
        ),
        plan=[],
        change=None,
        groups=[],
        built=set(),
        ceiling=750,
        floor=ordinary_floor,
    )


@pytest.mark.parametrize(("group_kind", "onto_kind"), ALLOWED)
def test_a_group_joins_a_unit_unless_one_of_them_is_e2e_test(
    group_kind: str, onto_kind: str
) -> None:
    check_group(group_kind, onto_kind)


@pytest.mark.parametrize(("taken_kind", "onto_kind"), ALLOWED)
def test_a_unit_joins_a_unit_unless_one_of_them_is_e2e_test(
    taken_kind: str, onto_kind: str
) -> None:
    check_unit(taken_kind, onto_kind)


@pytest.mark.parametrize(("group_kind", "onto_kind"), REFUSED)
def test_an_e2e_test_group_or_unit_is_refused_with_each_of_the_others(
    group_kind: str, onto_kind: str
) -> None:
    with pytest.raises(JoinRefused, match=r"is tagged \[app\]"):
        check_group(group_kind, onto_kind)
    with pytest.raises(JoinRefused, match="another repo or tier"):
        check_unit(group_kind, onto_kind)


@pytest.mark.parametrize(("group_kind", "onto_kind"), [(UNIT, INTEGRATION), (INTEGRATION, UNIT)])
def test_the_survivor_of_a_group_join_takes_the_widest_kind(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    group_kind: str,
    onto_kind: str,
) -> None:
    run = Replan(tmp_path, monkeypatch, base=tagged_md(onto_kind), feature=tagged_md(group_kind))
    run.store.upsert([stored_unit("base/1", change="base", tier=onto_kind, groups=(1,))])
    run.record("base")
    join = {"onto": "base/1", "change": "feature", "groups": [1], "estimated_lines": 80}

    code, out = run.run(capsys, "feature", reply=answer(joins=[join]))

    assert code == 0, out
    assert run.store.get("base/1").tier == INTEGRATION


def test_the_survivor_of_a_unit_join_takes_the_widest_kind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(
        tmp_path,
        monkeypatch,
        base=tagged_md(UNIT),
        later=tagged_md(INTEGRATION),
        other=tagged_md(UNIT),
    )
    run.store.upsert(
        [
            stored_unit("base/1", change="base", tier=UNIT, groups=(1,)),
            stored_unit(
                "later/1", change="later", tier=INTEGRATION, groups=(1,), depends_on=("base/1",)
            ),
        ]
    )
    run.record("base")
    run.record("later")
    join = {"onto": "base/1", "unit": "later/1"}

    code, out = run.run(
        capsys, "other", reply=answer(dict(planned("other/1", (1,)), tier=UNIT), joins=[join])
    )

    assert code == 0, out
    assert run.store.get("base/1").tier == INTEGRATION


def test_a_replan_of_the_receiving_change_keeps_the_kind_a_joined_group_widened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, base=tagged_md(UNIT), feature=tagged_md(INTEGRATION))
    run.store.upsert([stored_unit("base/1", change="base", tier=UNIT, groups=(1,))])
    run.record("base")
    join = dict(onto="base/1", change="feature", groups=[1], estimated_lines=80)
    code, out = run.run(capsys, "feature", reply=answer(joins=[join]))
    assert code == 0, out
    assert run.store.get("base/1").tier == INTEGRATION

    run.write("base", tagged_md(UNIT).replace("Group 1", "Group one"))
    code, out = run.run(capsys, "base", reply=answer(dict(planned("base/1", (1,)), tier=UNIT)))

    assert code == 0, out
    assert run.store.get("base/1").tier == INTEGRATION
