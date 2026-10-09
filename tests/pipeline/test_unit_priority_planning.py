"""A unit's priority is set by the planner, in code, from the groups it builds.

Each case runs through `plan_all` with the planner's runtime answering in the
raw shape a model sends. The model is never asked for a priority: it comes from
the `Priority:` lines of every group the unit builds, carried groups included,
and the most urgent (smallest) wins.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from agent_build_kit import runtimes
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import PLANNED, Member
from tests.conftest import make_installation
from tests.factories import stored_unit
from tests.runtimes.stand_in import StandInRuntime

pytestmark = pytest.mark.usefixtures("scripted_engine")

OPT_OUT = "Acceptance: none — a fixture about priorities\n"


def tasks_md(*priorities: int | None, default: int | None = None) -> str:
    """One app group per entry, with that `Priority:` line (none for no line)."""
    text = f"# Tasks\n\n{OPT_OUT}\n"
    text += f"Priority: {default}\n\n" if default is not None else ""
    for number, value in enumerate(priorities, start=1):
        text += f"## {number}. [app] [tier1] Group {number}\n\n"
        text += f"Priority: {value}\n\n" if value is not None else ""
        text += f"- [ ] {number}.1 Test: it.\n- [ ] {number}.2 Do it.\n\n"
    return text


def planned(uid: str, groups: tuple[int, ...]) -> dict:
    return {
        "id": uid,
        "change": uid.split("/")[0],
        "title": "A unit",
        "repo": "app",
        "tier": "tier1",
        "depends_on": [],
        "estimated_lines": 80,
        "groups": list(groups),
    }


def answer(*units: dict, joins: list[dict] | None = None) -> str:
    return "Here is the plan.\n\n" + json.dumps({"units": list(units), "joins": joins or []})


class Round:
    def __init__(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tasks: dict[str, str]
    ) -> None:
        self.inst = make_installation(
            tmp_path, planning={"state_dir": ".", "worktree_root": str(tmp_path.parent / "trees")}
        )
        for change, text in tasks.items():
            (self.inst.changes_dir / change).mkdir(parents=True)
            (self.inst.changes_dir / change / "tasks.md").write_text(text)
        self.store = UnitStore(tmp_path / "units.json")
        self.runtime = StandInRuntime()
        monkeypatch.setattr(runtimes, "active", lambda: self.runtime)

    def plan(self, reply: str) -> None:
        self.runtime.answer = reply
        cli.plan_all(self.inst, store=self.store)

    def priority(self, uid: str) -> int:
        return self.store.get(uid).priority


def test_a_unit_with_no_priority_line_is_normal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = Round(tmp_path, monkeypatch, {"feature": tasks_md(None)})

    run.plan(answer(planned("feature/1", (1,))))

    assert run.priority("feature/1") == 3


def test_a_unit_takes_its_groups_priority(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run = Round(tmp_path, monkeypatch, {"feature": tasks_md(2, 5)})

    run.plan(answer(planned("feature/1", (1,)), planned("feature/2", (2,))))

    assert (run.priority("feature/1"), run.priority("feature/2")) == (2, 5)


def test_a_unit_takes_the_changes_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run = Round(tmp_path, monkeypatch, {"feature": tasks_md(None, 1, default=4)})

    run.plan(answer(planned("feature/1", (1,)), planned("feature/2", (2,))))

    assert (run.priority("feature/1"), run.priority("feature/2")) == (4, 1)


@pytest.mark.parametrize(("first", "second"), [(4, 2), (2, 4), (3, 3)])
def test_a_unit_of_several_groups_takes_the_most_urgent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, first: int, second: int
) -> None:
    run = Round(tmp_path, monkeypatch, {"feature": tasks_md(first, second)})

    run.plan(answer(planned("feature/1", (1, 2))))

    assert run.priority("feature/1") == min(first, second)


def start_unit_of_base(run: Round, priority: int) -> None:
    run.store.upsert([stored_unit("base/1", change="base", groups=(1,), priority=priority)])


@pytest.mark.parametrize(
    ("base", "carried", "expected"),
    [(4, 1, 1), (3, 5, 3), (1, 4, 1), (5, 2, 2)],
)
def test_a_unit_that_takes_in_a_changes_groups_takes_the_most_urgent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, base: int, carried: int, expected: int
) -> None:
    run = Round(
        tmp_path,
        monkeypatch,
        {"base": tasks_md(base), "feature": tasks_md(carried)},
    )
    start_unit_of_base(run, base)
    mark_planned(run, "base")

    run.plan(
        answer(
            joins=[{"onto": "base/1", "change": "feature", "groups": [1], "estimated_lines": 80}]
        )
    )

    assert [m.change for m in run.store.get("base/1").members()] == ["base", "feature"]
    assert run.priority("base/1") == expected


def mark_planned(run: Round, change: str) -> None:
    """Record the change as planned as it stands, so planning leaves it be."""
    text = cli.specification(run.inst.changes_dir / change / "tasks.md")
    record = {"hash": hashlib.sha256(text.encode()).hexdigest(), "attempts": 0, "ok": True}
    (run.inst.state_dir / "planned.json").write_text(json.dumps({change: record}))


def two_units_in_one_change(run: Round) -> None:
    run.plan(answer(planned("feature/1", (1,)), planned("feature/2", (2,))))


def test_an_edited_line_reaches_the_units_that_have_not_started(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = Round(tmp_path, monkeypatch, {"feature": tasks_md(None, None)})
    two_units_in_one_change(run)
    # A branch with no commit is a start the plan can still propose again.
    run.store.set_state("feature/1", PLANNED, branch="spec/feature/1")
    path = run.inst.changes_dir / "feature" / "tasks.md"
    path.write_text(tasks_md(1, 1))

    two_units_in_one_change(run)

    assert run.priority("feature/1") == 3
    assert run.priority("feature/2") == 1


@pytest.mark.parametrize(("carrier_has_branch", "expected"), [(False, 1), (True, 3)])
def test_an_edited_line_reaches_an_unstarted_unit_carrying_the_changes_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, carrier_has_branch: bool, expected: int
) -> None:
    run = Round(tmp_path, monkeypatch, {"base": tasks_md(3), "feature": tasks_md(3, 3)})
    run.store.upsert(
        [
            stored_unit(
                "base/1",
                change="base",
                groups=(1,),
                joined=(Member(change="feature", groups=(1,)),),
            )
        ]
    )
    if carrier_has_branch:
        run.store.set_state("base/1", PLANNED, branch="spec/base/1")
    mark_planned(run, "base")
    (run.inst.changes_dir / "feature" / "tasks.md").write_text(tasks_md(1, 3))

    run.plan(answer(planned("feature/2", (2,))))

    assert run.priority("base/1") == expected
