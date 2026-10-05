"""The planner joins small related sequential work.

Planning a change also looks at every unit that has not started and may join
two of them: a new change's groups onto an existing unit, or one existing unit
onto another. Each case runs through `plan_all` with the planner's runtime
answering in the raw shape a model sends — prose around a JSON object whose
`joins` list names the unit that stays (`onto`) and either a new change's
groups (`change`, `groups`, `estimated_lines`) or the existing unit taken in
(`unit`).
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit import runtimes
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.stack_runner import RunOutcome
from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.units import (
    CLOSED,
    FAILED,
    HELD,
    IN_REVIEW,
    MERGED,
    RUNNING,
    SATISFIED,
    Join,
    Member,
    Unit,
)
from tests.conftest import make_installation
from tests.factories import stored_unit
from tests.runtimes.stand_in import StandInRuntime

OPT_OUT = "Acceptance: none — a fixture about planning, not about the acceptance group\n"


# --- fixtures ------------------------------------------------------------------

pytestmark = pytest.mark.usefixtures("scripted_engine")


def group(**overrides: Any) -> dict[str, Any]:
    return {"repo": "app", "tier": "tier1", "flag": "", "extra": "", **overrides}


def tasks_md(*groups: dict[str, Any]) -> str:
    """A change's tasks.md. Opts out of the acceptance group unless it has one."""
    groups = groups or (group(),)
    text = "# Tasks\n\n"
    if not any(g["flag"] == "acceptance" for g in groups):
        text += OPT_OUT + "\n"
    for number, g in enumerate(groups, start=1):
        flag = f" [{g['flag']}]" if g["flag"] else ""
        text += f"## {number}. [{g['repo']}] [{g['tier']}]{flag} Group {number}\n\n"
        text += f"{g['extra']}\n" if g["extra"] else ""
        text += f"- [ ] {number}.1 Test: it.\n- [ ] {number}.2 Do it.\n\n"
    return text


def answer(units: list[dict] | None = None, joins: list[dict] | None = None) -> str:
    return "Here is the plan.\n\n" + json.dumps({"units": units or [], "joins": joins or []})


def new_unit(uid: str = "feature/1", groups: tuple[int, ...] = (1,), **overrides: Any) -> dict:
    return {
        "id": uid,
        "change": uid.split("/")[0],
        "title": "A unit",
        "repo": "app",
        "tier": "tier1",
        "depends_on": [],
        "estimated_lines": 80,
        "groups": list(groups),
        **overrides,
    }


def start(store: UnitStore, uid: str, kind: str) -> None:
    """Make a planned unit into one that has started, in the way `kind` says."""
    branch = f"spec/{uid}"
    if kind in (RUNNING, FAILED, HELD, MERGED, CLOSED, SATISFIED):
        store.set_state(uid, kind, branch=branch)
    elif kind == IN_REVIEW:
        store.set_state(uid, IN_REVIEW, branch=branch, pr=4)
    elif kind == "planned":
        pass  # unfinished but unstarted: the unit is left as it was planned
    elif kind == "branch":
        store.set_state(uid, "planned", branch=branch)
    elif kind == "pull-request":
        store.set_state(uid, "planned", pr=4)
    elif kind == "pushed-commit":
        store.record_push(uid, "abc1234")
    elif kind == "approved-commit":
        store.record_approval(uid, "abc1234")
    else:
        raise AssertionError(kind)


STARTED = [
    RUNNING,
    IN_REVIEW,
    MERGED,
    CLOSED,
    SATISFIED,
    FAILED,
    HELD,
    "branch",
    "pull-request",
    "pushed-commit",
    "approved-commit",
]


def mark_planned(inst: Installation, changes: list[str]) -> None:
    """Record these changes as planned as they stand, so a tick leaves them be."""
    records = {
        change: {
            "hash": hashlib.sha256(
                cli.specification(inst.changes_dir / change / "tasks.md").encode()
            ).hexdigest(),
            "attempts": 0,
            "ok": True,
        }
        for change in changes
    }
    (inst.state_dir / "planned.json").write_text(json.dumps(records))


class Run:
    def __init__(self, inst: Installation, store: UnitStore, runtime: StandInRuntime) -> None:
        self.inst = inst
        self.store = store
        self.runtime = runtime

    def ids(self) -> list[str]:
        return sorted(u.id for u in self.store.all())

    def plan(self) -> None:
        cli.plan_all(self.inst, store=self.store)


def set_up(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    units: list[StoredUnit],
    tasks: dict[str, str],
    planning: str,
    reply: str,
    started: dict[str, str] | None = None,
    act: Callable[[UnitStore], None] | None = None,
) -> Run:
    """A planning repo holding `units` and these changes' tasks, with `planning`
    the only change not yet planned, and a planner that answers `reply`."""
    inst = make_installation(
        tmp_path, planning={"state_dir": ".", "worktree_root": str(tmp_path.parent / "trees")}
    )
    for change, text in tasks.items():
        path = inst.changes_dir / change
        path.mkdir(parents=True)
        (path / "tasks.md").write_text(text)
    mark_planned(inst, [c for c in tasks if c != planning])

    store = UnitStore(tmp_path / "units.json")
    store.upsert(units)
    for uid, kind in (started or {}).items():
        start(store, uid, kind)

    runtime = StandInRuntime(
        answer=reply, act=(lambda request: act(store)) if act is not None else None
    )
    monkeypatch.setattr(runtimes, "active", lambda: runtime)
    return Run(inst, store, runtime)


def carried(run: Run, uid: str) -> dict[str, list[int]]:
    """The groups `uid` builds, per change, however the unit records them."""
    found: dict[str, list[int]] = {}
    for member in run.store.get(uid).members():
        found.setdefault(member.change, []).extend(member.groups)
    return {change: sorted(numbers) for change, numbers in found.items()}


# --- one new change's groups onto an existing unit -------------------------------


def onto_base(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **v: Any) -> Run:
    """`feature`'s one group, to be carried by the unstarted `base/1`."""
    feature_group = group(**v.get("feature_group", {}))
    units = [
        stored_unit(
            "base/1",
            change="base",
            groups=(1,),
            estimated_lines=100,
            tier=v.get("base_tier", "tier1"),
        )
    ]
    if v.get("dependent"):
        units.append(stored_unit("z/1", change="z", groups=(1,), depends_on=("base/1",)))
    if v.get("other"):
        units.append(stored_unit("other/1", change="other", groups=(1,)))
    tasks = {
        "base": tasks_md(*v.get("base_groups", [group(**v.get("base_group", {}))])),
        "feature": tasks_md(feature_group),
    }
    reply = answer(
        joins=[
            {
                "onto": "base/1",
                "change": "feature",
                "groups": [1],
                "estimated_lines": v.get("estimate", 80),
            }
        ]
    )
    return set_up(
        tmp_path,
        monkeypatch,
        units=units,
        tasks=tasks,
        planning="feature",
        reply=reply,
        started={"other/1": v["other"]} if v.get("other") else None,
    )


def test_a_new_changes_group_is_carried_by_an_unstarted_unit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = onto_base(tmp_path, monkeypatch)

    run.plan()

    assert carried(run, "base/1") == {"base": [1], "feature": [1]}
    assert run.ids() == ["base/1"]


def test_a_finished_dependency_does_not_stop_a_join(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = onto_base(
        tmp_path,
        monkeypatch,
        other=MERGED,
        feature_group={"extra": "Needs: other group 1 — it adds the field"},
    )

    run.plan()

    assert carried(run, "base/1") == {"base": [1], "feature": [1]}


NEW_GROUP_REFUSED = {
    "repo": {"feature_group": {"repo": "platform"}},
    "tier": {"feature_group": {"tier": "tier2"}},
    "something depends on the unit": {"dependent": True},
    "waits on other unfinished work": {
        "other": "planned",
        "feature_group": {"extra": "Needs: other group 1 — it adds the field"},
    },
    "narrowing group joined": {"feature_group": {"flag": "narrow"}},
    "narrowing group joined onto": {"base_group": {"flag": "narrow"}},
    "contract group joined onto": {"base_groups": [group(flag="contract"), group(flag="narrow")]},
    "acceptance group joined": {
        "feature_group": {"tier": "tier2", "flag": "acceptance"},
        "base_tier": "tier2",
    },
    "acceptance group joined onto": {
        "base_group": {"tier": "tier2", "flag": "acceptance"},
        "base_tier": "tier2",
        "feature_group": {"tier": "tier2"},
    },
    "over the ceiling": {"estimate": 950},
    "joined group is separate": {"feature_group": {"extra": "Separate: reviewed alone"}},
    "joined onto group is separate": {"base_group": {"extra": "Separate: reviewed alone"}},
    "joined onto group is independent": {
        "base_group": {"extra": "Independent: only adds a receiver"}
    },
}

# The words of the rule each variation breaks, so a variation that one day trips
# another rule fails instead of passing for the wrong reason.
NEW_GROUP_REASON = {
    "repo": "is tagged [platform]",
    "tier": "is tagged [app] [tier2]",
    "something depends on the unit": "already depends on base/1",
    "waits on other unfinished work": "also waits on other group 1",
    "narrowing group joined": "flagged [narrow]",
    "narrowing group joined onto": "flagged [narrow]",
    "contract group joined onto": "flagged [contract]",
    "acceptance group joined": "flagged [acceptance]",
    "acceptance group joined onto": "flagged [acceptance]",
    "over the ceiling": "over the ceiling",
    "joined group is separate": "marked `Separate:`",
    "joined onto group is separate": "marked `Separate:`",
    "joined onto group is independent": "marked `Independent:`",
}
assert NEW_GROUP_REASON.keys() == NEW_GROUP_REFUSED.keys()


@pytest.mark.parametrize("variation", list(NEW_GROUP_REFUSED))
def test_a_join_that_breaks_a_rule_is_refused(
    variation: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    run = onto_base(tmp_path, monkeypatch, **NEW_GROUP_REFUSED[variation])
    before = run.ids()

    run.plan()

    assert run.ids() == before
    assert run.store.get("base/1").joined == ()
    assert NEW_GROUP_REASON[variation] in capsys.readouterr().out


@pytest.mark.parametrize("kind", STARTED)
def test_a_new_group_is_not_joined_onto_a_unit_that_has_started(
    kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    run = onto_base(tmp_path, monkeypatch)
    start(run.store, "base/1", kind)
    before = run.store.get("base/1")

    run.plan()

    assert run.store.get("base/1") == before
    assert run.ids() == ["base/1"]
    assert "join" in capsys.readouterr().out.lower()


def test_a_unit_that_starts_while_the_plan_is_made_drops_only_that_join(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Group 1 was to be carried by `base/1`, which begins building after the
    planner has answered. It is not disturbed; group 2's own unit is written;
    group 1 is planned again on a later round."""
    run = set_up(
        tmp_path,
        monkeypatch,
        units=[stored_unit("base/1", change="base", groups=(1,), estimated_lines=100)],
        tasks={"base": tasks_md(), "feature": tasks_md(group(), group())},
        planning="feature",
        reply=answer(
            units=[new_unit("feature/1", (2,), depends_on=["base/1"])],
            joins=[{"onto": "base/1", "change": "feature", "groups": [1], "estimated_lines": 80}],
        ),
        act=lambda store: store.set_state("base/1", RUNNING, branch="spec/base/1"),
    )

    run.plan()

    started = run.store.get("base/1")
    assert started.state == RUNNING
    assert started.joined == ()
    assert started.estimated_lines == 100
    assert run.ids() == ["base/1", "feature/1"]
    assert run.store.get("feature/1").groups == (2,)

    run.plan()

    assert len(run.runtime.requests) == 2


# --- two existing units ---------------------------------------------------------


def chain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **v: Any) -> Run:
    """`b/1` waits only on `a/1`, both unstarted and small; `feature` is the
    change being planned, with a unit of its own."""
    b_depends = ["a/1"]
    units = [
        stored_unit(
            "a/1",
            change="a",
            groups=(1,),
            estimated_lines=100,
            repo=v.get("a_repo", "app"),
            tier=v.get("a_tier", "tier1"),
        ),
        stored_unit(
            "b/1",
            change=v.get("b_change", "b"),
            groups=v.get("b_groups", (1,)),
            estimated_lines=v.get("b_estimate", 120),
            repo=v.get("b_repo", "app"),
            tier=v.get("b_tier", "tier1"),
            depends_on=tuple(b_depends),
        ),
    ]
    started: dict[str, str] = {}
    if other := v.get("other"):
        units.append(stored_unit("x/1", change="x", groups=(1,)))
        b_depends.append("x/1")
        started["x/1"] = other
    units[1] = units[1].model_copy(update={"depends_on": tuple(b_depends)})
    if v.get("dependent"):
        units.append(stored_unit("z/1", change="z", groups=(1,), depends_on=("a/1",)))
    if v.get("after_b"):
        units.append(stored_unit("d/1", change="d", groups=(1,), depends_on=("b/1",)))
    tasks = {
        "a": tasks_md(*v.get("a_groups", [group(**v.get("a_group", {}))])),
        "feature": tasks_md(),
    }
    if v.get("b_change", "b") != "a":
        tasks[v.get("b_change", "b")] = tasks_md(
            *v.get("b_groups_md", [group(**v.get("b_group", {}))])
        )
    else:
        tasks["a"] = tasks_md(group(), group())
    return set_up(
        tmp_path,
        monkeypatch,
        units=units,
        tasks=tasks,
        planning="feature",
        reply=answer(units=[new_unit()], joins=[{"onto": "a/1", "unit": "b/1"}]),
        started=started,
    )


def test_two_unstarted_units_of_different_changes_are_joined(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = chain(tmp_path, monkeypatch)

    run.plan()

    assert run.ids() == ["a/1", "feature/1"]
    assert carried(run, "a/1") == {"a": [1], "b": [1]}
    assert [m.change for m in run.store.get("a/1").members()] == ["a", "b"]
    assert run.store.get("a/1").estimated_lines == 220


def test_two_unstarted_units_of_one_change_are_joined(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = chain(tmp_path, monkeypatch, b_change="a", b_groups=(2,))

    run.plan()

    assert run.ids() == ["a/1", "feature/1"]
    assert carried(run, "a/1") == {"a": [1, 2]}


def test_a_unit_that_depended_on_the_one_joined_away_depends_on_the_one_that_took_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = chain(tmp_path, monkeypatch, after_b=True)

    run.plan()

    assert run.ids() == ["a/1", "d/1", "feature/1"]
    assert run.store.get("d/1").depends_on == ("a/1",)


def test_a_finished_unit_the_later_also_waited_on_does_not_stop_the_join(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = chain(tmp_path, monkeypatch, other=MERGED)

    run.plan()

    assert carried(run, "a/1") == {"a": [1], "b": [1]}
    assert "b/1" not in run.ids()


CHAIN_REFUSED = {
    "repo": {"b_repo": "platform", "b_group": {"repo": "platform"}},
    "tier": {"b_tier": "tier2", "b_group": {"tier": "tier2"}},
    "something else depends on the earlier": {"dependent": True},
    "the later waits on other unfinished work": {"other": "planned"},
    "earlier narrowing": {"a_group": {"flag": "narrow"}},
    "later narrowing": {"b_group": {"flag": "narrow"}},
    "earlier contract": {"a_groups": [group(flag="contract"), group(flag="narrow")]},
    "earlier acceptance": {
        "a_group": {"tier": "tier2", "flag": "acceptance"},
        "a_tier": "tier2",
        "b_tier": "tier2",
        "b_group": {"tier": "tier2"},
    },
    "later acceptance": {
        "b_group": {"tier": "tier2", "flag": "acceptance"},
        "a_tier": "tier2",
        "b_tier": "tier2",
        "a_group": {"tier": "tier2"},
    },
    "over the ceiling": {"b_estimate": 950},
    "earlier separate": {"a_group": {"extra": "Separate: reviewed alone"}},
    "later separate": {"b_group": {"extra": "Separate: reviewed alone"}},
    "earlier independent": {"a_group": {"extra": "Independent: only adds a receiver"}},
    "later independent": {"b_group": {"extra": "Independent: only adds a receiver"}},
}

CHAIN_REASON = {
    "repo": "is in another repo or tier",
    "tier": "is in another repo or tier",
    "something else depends on the earlier": "already depends on a/1",
    "the later waits on other unfinished work": "also waits on x/1",
    "earlier narrowing": "flagged [narrow]",
    "later narrowing": "flagged [narrow]",
    "earlier contract": "flagged [contract]",
    "earlier acceptance": "flagged [acceptance]",
    "later acceptance": "flagged [acceptance]",
    "over the ceiling": "over the ceiling",
    "earlier separate": "marked `Separate:`",
    "later separate": "marked `Separate:`",
    "earlier independent": "marked `Independent:`",
    "later independent": "marked `Independent:`",
}
assert CHAIN_REASON.keys() == CHAIN_REFUSED.keys()


@pytest.mark.parametrize("variation", list(CHAIN_REFUSED))
def test_a_join_of_two_units_that_breaks_a_rule_is_refused(
    variation: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    run = chain(tmp_path, monkeypatch, **CHAIN_REFUSED[variation])
    before = run.ids()

    run.plan()

    assert run.ids() == before
    assert run.store.get("a/1").joined == ()
    assert CHAIN_REASON[variation] in capsys.readouterr().out


@pytest.mark.parametrize("uid", ["a/1", "b/1"])
@pytest.mark.parametrize("kind", STARTED)
def test_a_unit_that_has_started_is_joined_to_nothing_on_either_side(
    uid: str,
    kind: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    run = chain(tmp_path, monkeypatch)
    start(run.store, uid, kind)
    before = run.store.all()

    run.plan()

    assert run.store.all() == before
    assert "join" in capsys.readouterr().out.lower()


def test_a_unit_that_starts_while_the_plan_is_made_is_left_with_the_one_it_was_to_join(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The same plan with nothing starting in between is written in full, so
    # what follows is the race and not a join that was never going to happen.
    control = chain(tmp_path / "control", monkeypatch)
    control.plan()
    assert carried(control, "a/1") == {"a": [1], "b": [1]}

    run = chain(tmp_path / "race", monkeypatch)
    run.runtime.act = lambda request: run.store.set_state("b/1", RUNNING, branch="spec/b/1")

    run.plan()

    assert run.ids() == ["a/1", "b/1", "feature/1"]
    assert run.store.get("a/1").joined == ()
    assert run.store.get("a/1").estimated_lines == 100
    assert run.store.get("b/1").state == RUNNING
    assert run.store.get("b/1").depends_on == ("a/1",)


def test_three_unstarted_units_in_a_line_become_one_in_a_round(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    units = [
        stored_unit("a/1", change="a", groups=(1,), estimated_lines=100),
        stored_unit("b/1", change="b", groups=(1,), estimated_lines=100, depends_on=("a/1",)),
        stored_unit("c/1", change="c", groups=(1,), estimated_lines=100, depends_on=("b/1",)),
        stored_unit("d/1", change="d", groups=(1,), estimated_lines=100, depends_on=("c/1",)),
    ]
    run = set_up(
        tmp_path,
        monkeypatch,
        units=units,
        tasks={c: tasks_md() for c in ("a", "b", "c", "d", "feature")},
        planning="feature",
        reply=answer(
            units=[new_unit()],
            joins=[
                {"onto": "a/1", "unit": "b/1"},
                {"onto": "a/1", "unit": "c/1"},
            ],
        ),
    )

    run.plan()

    assert run.ids() == ["a/1", "d/1", "feature/1"]
    assert [m.change for m in run.store.get("a/1").members()] == ["a", "b", "c"]
    assert run.store.get("a/1").estimated_lines == 300
    assert run.store.get("d/1").depends_on == ("a/1",)


# --- a unit that is joined to again --------------------------------------------


def joined_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, later_estimate: int) -> Run:
    units = [
        stored_unit(
            "a/1",
            change="a",
            groups=(1,),
            estimated_lines=400,
            joined=(Member(change="b", groups=(1,)),),
        ),
        stored_unit(
            "c/1", change="c", groups=(1,), estimated_lines=later_estimate, depends_on=("a/1",)
        ),
    ]
    return set_up(
        tmp_path,
        monkeypatch,
        units=units,
        tasks={c: tasks_md() for c in ("a", "b", "c", "feature")},
        planning="feature",
        reply=answer(units=[new_unit()], joins=[{"onto": "a/1", "unit": "c/1"}]),
    )


def test_a_unit_joined_to_once_is_joined_to_again_while_under_the_ceiling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = joined_once(tmp_path, monkeypatch, later_estimate=300)

    run.plan()

    assert run.ids() == ["a/1", "feature/1"]
    assert [m.change for m in run.store.get("a/1").members()] == ["a", "b", "c"]
    assert run.store.get("a/1").estimated_lines == 700


def test_a_unit_joined_to_once_is_refused_a_join_that_passes_the_ceiling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    run = joined_once(tmp_path, monkeypatch, later_estimate=700)

    run.plan()

    assert run.ids() == ["a/1", "c/1"]
    assert run.store.get("a/1").estimated_lines == 400
    assert "join" in capsys.readouterr().out.lower()


# --- planning a joined-away unit's change again ---------------------------------


def carrying_feature(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reply: str) -> Run:
    return set_up(
        tmp_path,
        monkeypatch,
        units=[
            stored_unit(
                "base/1",
                change="base",
                groups=(1,),
                estimated_lines=180,
                joined=(Member(change="feature", groups=(1,)),),
            )
        ],
        tasks={"base": tasks_md(), "feature": tasks_md()},
        planning="feature",
        reply=reply,
    )


def test_planning_a_change_again_creates_no_unit_for_groups_another_unit_carries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    run = carrying_feature(tmp_path, monkeypatch, answer())
    before = run.store.all()

    run.plan()

    assert len(run.runtime.requests) == 1
    assert run.store.all() == before
    assert "failed" not in capsys.readouterr().out


def test_a_unit_claiming_a_group_another_unit_carries_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = carrying_feature(tmp_path, monkeypatch, answer(units=[new_unit()]))

    run.plan()

    assert run.ids() == ["base/1"]


# --- what the planner is told ---------------------------------------------------


def test_the_planner_is_shown_which_units_have_not_started(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = set_up(
        tmp_path,
        monkeypatch,
        units=[
            stored_unit("base/1", change="base", groups=(1,)),
            stored_unit("busy/1", change="busy", groups=(1,)),
        ],
        tasks={c: tasks_md() for c in ("base", "busy", "feature")},
        planning="feature",
        reply=answer(units=[new_unit()]),
        started={"busy/1": IN_REVIEW},
    )

    run.plan()

    prompt = run.runtime.request.prompt
    shown = {
        uid: [line for line in prompt.splitlines() if uid in line] for uid in ("base/1", "busy/1")
    }
    assert shown["base/1"], "the unstarted unit is not in the prompt"
    assert shown["busy/1"], "the unit in review is not in the prompt"
    assert all("unstarted" in line for line in shown["base/1"])
    assert not any("unstarted" in line for line in shown["busy/1"])
    assert '"joins"' in prompt


# --- the log --------------------------------------------------------------------


def test_a_join_of_new_groups_is_logged_with_the_unit_and_the_estimates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    run = onto_base(tmp_path, monkeypatch)

    run.plan()

    assert "joined feature group(s) 1 onto base/1 — est 100+80=180" in capsys.readouterr().out


def test_a_join_of_two_units_is_logged_with_both_and_the_estimates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    run = chain(tmp_path, monkeypatch)

    run.plan()

    lines = [line for line in capsys.readouterr().out.splitlines() if "joined" in line]
    assert len(lines) == 1
    assert "a/1" in lines[0]
    assert "b/1" in lines[0]
    assert "est 100+120=220" in lines[0]


# --- keeping a group separate, through `abk tags` --------------------------------


def test_abk_tags_rejects_a_separate_line_without_a_reason(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    inst = make_installation(tmp_path)
    path = inst.changes_dir / "feature"
    path.mkdir(parents=True)
    (path / "tasks.md").write_text(
        tasks_md(group(extra="Separate:")),
    )

    status = cli.cmd_tags(argparse.Namespace(change="feature", all=False), inst)

    assert status == 1
    assert "Separate" in capsys.readouterr().out


# --- what started or overlapping work sees of a join ---------------------------


def test_a_started_unit_that_carries_a_group_is_shown_to_the_planner_as_building_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = carrying_feature(tmp_path, monkeypatch, answer())
    start(run.store, "base/1", IN_REVIEW)

    run.plan()

    lines = [line for line in run.runtime.request.prompt.splitlines() if "base/1" in line]
    assert lines, "the unit in review is not in the prompt"
    assert all("feature group(s) 1" in line for line in lines)
    assert not any("unstarted" in line for line in lines)


def test_planning_the_carrying_units_change_without_it_plans_the_carried_change_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`base/1` carries `feature` group 1. Planning `base` without `base/1`
    demotes it, and nothing else would build that group, so `feature` is
    planned again."""
    run = set_up(
        tmp_path,
        monkeypatch,
        units=[
            stored_unit(
                "base/1",
                change="base",
                groups=(1,),
                estimated_lines=180,
                joined=(Member(change="feature", groups=(1,)),),
            )
        ],
        tasks={"base": tasks_md(), "feature": tasks_md()},
        planning="base",
        reply=answer(units=[new_unit("base/2", (1,))]),
    )
    assert "feature" in json.loads((run.inst.state_dir / "planned.json").read_text())

    run.plan()

    assert run.store.get("base/1").state == "unplanned"
    # `feature` is asked for again — here in the same pass, as it comes after
    # `base` — instead of being left recorded as planned.
    asked = [r.prompt for r in run.runtime.requests]
    assert len(asked) == 2
    assert "### base" in asked[0]
    assert "### feature" in asked[1]


def test_a_unit_taken_by_a_join_since_the_tick_listed_it_is_skipped_not_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    run = chain(tmp_path, monkeypatch)
    listed = run.store.get("b/1")
    assert run.store.join(Join(onto="a/1", unit="b/1")) is not None
    monkeypatch.setattr(
        cli, "build_runner", lambda unit, **kw: pytest.fail("built a unit that was joined away")
    )

    assert cli.build_unit(run.inst, listed, store=run.store) is True

    out = capsys.readouterr().out
    assert "joined into another unit" in out
    assert "failed" not in out


def test_a_build_runs_the_members_a_join_gave_the_unit_after_the_tick_listed_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = chain(tmp_path, monkeypatch)
    listed = run.store.get("a/1")
    assert run.store.join(Join(onto="a/1", unit="b/1")) is not None
    built: list[Unit] = []

    class Recording:
        def run(self, unit: Unit, *, base: str, graph: list) -> RunOutcome:
            built.append(unit)
            return RunOutcome(status="open", detail="opened")

    monkeypatch.setattr(cli, "build_runner", lambda unit, **kw: Recording())

    cli.build_unit(run.inst, listed, store=run.store)

    assert [m.change for m in built[0].members()] == ["a", "b"]


def test_a_replan_of_the_carrying_unit_keeps_the_estimate_of_what_it_carries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = set_up(
        tmp_path,
        monkeypatch,
        units=[
            stored_unit(
                "base/1",
                change="base",
                groups=(1,),
                estimated_lines=400,
                joined=(Member(change="feature", groups=(1,)),),
            )
        ],
        tasks={"base": tasks_md(), "feature": tasks_md()},
        planning="base",
        reply=answer(units=[new_unit("base/1", (1,), estimated_lines=100)]),
    )

    run.plan()

    assert run.store.get("base/1").estimated_lines == 400
    assert carried(run, "base/1") == {"base": [1], "feature": [1]}
