"""The promotion of an unstarted prerequisite runs where the plan or the links change who waits.

`plan_all` writes the plan's default priority and then the group's own, so it ends with the
promotion; the tick and `abk replan` run it after the `Needs:` lines are linked
(spec: unit-scheduling).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from tests.cli.replan_driver import OPT_OUT, Replan, answer, planned
from tests.tick_pass import install_builder, isolate, stored, tick, warm_unit_graphs, workspace

pytestmark = pytest.mark.usefixtures("scripted_engine")

REASONED = answer(
    planned("feature/1", (1,)),
    {
        **planned("feature/2", (2,), depends_on=("feature/1",)),
        "needs_less_urgent": {"feature/1": "it adds the helper"},
    },
)


def two_groups(first: int, second: int) -> str:
    text = f"# Tasks\n\n{OPT_OUT}\n"
    for number, value in ((1, first), (2, second)):
        text += f"## {number}. [app] [unit-test] Group {number}\n\nPriority: {value}\n\n"
        text += f"- [ ] {number}.1 Test: it.\n- [ ] {number}.2 Do it.\n\n"
    return text


def one_group(priority: int) -> str:
    return (
        f"# Tasks\n\n{OPT_OUT}\n## 1. [app] [unit-test] The work\n\nPriority: {priority}\n\n"
        "- [ ] 1.1 Test: it.\n- [ ] 1.2 Do it.\n"
    )


def needing(priority: int, target: str) -> str:
    return (
        f"# Tasks\n\n{OPT_OUT}\n## 1. [app] [unit-test] The work\n\nPriority: {priority}\n"
        f"Needs: {target} group 1 — a reason\n\n- [ ] 1.1 Test: it.\n- [ ] 1.2 Do it.\n"
    )


def promoted(store, unit_id: str) -> tuple[int, str]:
    found = store.get(unit_id)
    return found.priority, found.promoted_from


def test_plan_all_leaves_the_ancestor_of_a_reasoned_edge_promoted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=two_groups(3, 1))
    run.runtime.answer = REASONED

    cli.plan_all(run.inst, store=run.store)

    assert promoted(run.store, "feature/1") == (1, "feature/2")
    assert promoted(run.store, "feature/2") == (1, "")


def test_a_later_replan_that_regenerates_the_ancestor_keeps_it_promoted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=two_groups(3, 1))
    run.runtime.answer = REASONED
    cli.plan_all(run.inst, store=run.store)

    cli.plan_all(run.inst, store=run.store, only={"feature"}, force=True)

    assert promoted(run.store, "feature/1") == (1, "feature/2")


def test_replan_promotes_the_target_of_a_needs_line_it_links(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, other=one_group(3), feature=needing(1, "other"))
    run.store.upsert([stored("other/1", change="other")])

    code, out = run.run(capsys, "feature", reply=answer(planned("feature/1", (1,))))

    assert code == 0
    assert run.store.get("feature/1").depends_on == ("other/1",)
    assert promoted(run.store, "other/1") == (1, "feature/1")
    line = next(line for line in out.splitlines() if "promot" in line)
    assert re.search(r"other/1.*\b1\b.*feature/1", line), line


def test_a_tick_promotes_the_target_of_a_needs_line_it_links(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    warm_unit_graphs(tmp_path)
    isolate(monkeypatch)
    builder = install_builder(tmp_path, monkeypatch)
    inst = workspace(tmp_path)
    for change, text in (("other", one_group(3)), ("feature", needing(1, "other"))):
        path = inst.changes_dir / change / "tasks.md"
        path.parent.mkdir(parents=True)
        path.write_text(text)
    builder.store.upsert([stored("other/1"), stored("feature/1")])
    capsys.readouterr()

    assert tick(inst) == 0

    out = capsys.readouterr().out
    assert builder.store.get("feature/1").depends_on == ("other/1",)
    assert promoted(builder.store, "other/1") == (1, "feature/1")
    line = next(line for line in out.splitlines() if "promot" in line)
    assert re.search(r"other/1.*\b1\b.*feature/1", line), line
