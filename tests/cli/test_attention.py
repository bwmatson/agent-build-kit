"""`abk attention` lists what needs a person, each with the command that acts on it, and leaves
out what resolves without anyone."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from agent_build_kit import run_support
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.cli.attention_cmd import attention_items
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import plan_review
from agent_build_kit.pipeline.plan_review import Finding, Review
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import FAILED, RUNNING
from tests.conftest import make_installation
from tests.factories import stored_unit

NOW = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)


def unit(uid: str, *, note: str = "", **overrides):
    """A stored unit of the change its id names; `note` is its last history entry's."""
    if note:
        overrides["history"] = (
            {"state": overrides.get("state", "planned"), "at": NOW.isoformat(), "note": note},
        )
    return stored_unit(uid, change=uid.partition("/")[0], **overrides)


def test_a_failed_unit_is_listed_with_how_many_units_it_holds_up(tmp_path: Path) -> None:
    inst = make_installation(tmp_path)
    failed = unit("a/1", state=FAILED, note="checks failing")
    waiting = unit("b/1", depends_on=("a/1",))

    [item] = attention_items(inst, [failed, waiting], idle=set(), now=NOW)

    assert item.subject == "a/1"
    assert item.blocks == 1
    assert "checks failing" in item.what
    assert "abk requeue a/1" in item.action


def test_a_failed_unit_waiting_on_a_dependency_is_left_out(tmp_path: Path) -> None:
    """It is requeued when the wait ends; nobody needs to act."""
    inst = make_installation(tmp_path)
    parent = unit("p/1")
    failed = unit("a/1", state=FAILED, depends_on=("p/1",))

    assert attention_items(inst, [parent, failed], idle=set(), now=NOW) == []


def test_a_running_unit_no_worker_has_held_for_an_hour_is_listed(tmp_path: Path) -> None:
    inst = make_installation(tmp_path)
    stale = unit(
        "a/1", state=RUNNING, history=({"state": RUNNING, "at": "2026-11-23T10:00:00+00:00"},)
    )
    fresh = unit(
        "b/1", state=RUNNING, history=({"state": RUNNING, "at": "2026-11-23T11:30:00+00:00"},)
    )

    items = attention_items(inst, [stale, fresh], idle={"a/1", "b/1"}, now=NOW)

    assert [item.subject for item in items] == ["a/1"]


def test_a_plan_hold_is_listed_only_while_the_change_has_units_not_started(
    tmp_path: Path,
) -> None:
    inst = make_installation(tmp_path)
    plan_review._record(
        plan_review.record_path(inst),
        "a",
        Review(hash="h", findings=(Finding(group=1, question=1, evidence="red at the end"),)),
    )
    started = unit("a/1", state=RUNNING, branch="spec/a/1")

    assert attention_items(inst, [started], idle=set(), now=NOW) == []

    [item] = attention_items(inst, [started, unit("a/2")], idle=set(), now=NOW)
    assert item.subject == "a"
    assert "abk review-plan show a" in item.action


def test_a_requeue_of_an_idle_running_unit_is_accepted(tmp_path: Path) -> None:
    """A running unit no run holds is waiting to resume: a requeue replaces what it was asked."""
    inst = make_installation(tmp_path)
    store = run_support.store_for(inst)
    store.upsert([unit("a/1")], change="a")
    store.set_state("a/1", RUNNING, cause=Cause.REQUEUED)

    assert cli.requeue(inst, "a/1", "resume", say=lambda *a, **k: None) == 0


def test_a_requeue_into_a_plan_hold_says_the_unit_will_wait(tmp_path: Path) -> None:
    inst = make_installation(tmp_path)
    store = run_support.store_for(inst)
    store.upsert([unit("a/1")], change="a")
    store.set_state("a/1", FAILED, cause=Cause.FAILED)
    plan_review._record(
        plan_review.record_path(inst),
        "a",
        Review(hash="h", findings=(Finding(group=1, question=1, evidence="red at the end"),)),
    )
    said: list[str] = []

    assert cli.requeue(inst, "a/1", "resume", say=lambda text, **_: said.append(text)) == 0

    assert any("will not start until the plan review of a is resolved" in line for line in said)


def write_outline(inst: Installation, name: str, *lines: str) -> None:
    folder = inst.root / "openspec/outlines" / name
    folder.mkdir(parents=True)
    (folder / "proposal.md").write_text(
        f"# {name}\n\nInitiative: grow — wave 1: {name}\n\n"
        "## Groups (sketch)\n1. [app] [unit-test] A\n\n" + "\n".join(lines) + "\n"
    )


def test_an_outline_ready_to_detail_is_listed_with_the_command_that_reads_it(
    tmp_path: Path,
) -> None:
    inst = make_installation(tmp_path, planning=dict(state_dir="."))
    (inst.changes_dir / "base").mkdir(parents=True)
    (inst.changes_dir / "base" / "tasks.md").write_text("## 1. [app] [unit-test] Work\n")
    running = stored_unit("base/1", change="base", groups=(1,), state=RUNNING)
    assert attention_items(inst, [running], idle=set(), now=NOW) == []
    write_outline(inst, "next", "Waits on: base group 1 — needs it")
    write_outline(inst, "far", "Waits on: base group 3 — needs it")

    items = attention_items(inst, [running], idle=set(), now=NOW)

    ready = [i for i in items if "next" in i.subject or "next" in i.what]
    assert len(ready) == 1
    assert "abk outlines" in ready[0].action
    assert not [i for i in items if "far" in i.subject or "far" in i.what]
