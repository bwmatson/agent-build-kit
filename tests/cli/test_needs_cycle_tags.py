"""`abk tags` and `abk check` report a cycle in the `Needs:` lines of two changes before
any planning (spec: planned-dependencies-never-close-a-cycle)."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit import openspec
from agent_build_kit.cli import pipeline as cli
from tests.cli.replan_driver import OPT_OUT, Replan, tasks_md

CYCLE = "checks-add-setting group 2 -> checks-hold-unit group 1 -> checks-add-setting group 2"


def two_changes_that_need_each_other(run: Replan) -> None:
    run.write("checks-add-setting", tasks_md(2, needs={2: "checks-hold-unit group 1"}))
    run.write("checks-hold-unit", tasks_md(1, needs={1: "checks-add-setting group 2"}))


def test_tags_all_prints_the_cycle_under_each_change_counts_it_and_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch)
    two_changes_that_need_each_other(run)

    status = cli.cmd_tags(argparse.Namespace(change=None, all=True), run.inst)

    lines = capsys.readouterr().out.splitlines()
    assert status == 1
    for change in ("checks-add-setting", "checks-hold-unit"):
        assert any(
            line.startswith(f"{change}:") and "Needs: cycle" in line and CYCLE in line
            for line in lines
        )
        assert f"1 problem(s) in {change}" in lines


def test_tags_for_one_change_names_the_same_cycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch)
    two_changes_that_need_each_other(run)

    status = cli.cmd_tags(argparse.Namespace(change="checks-hold-unit", all=False), run.inst)

    out = capsys.readouterr().out
    assert status == 1
    assert CYCLE in out


def test_check_prints_the_cycle_after_the_openspec_output_and_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch)
    two_changes_that_need_each_other(run)
    monkeypatch.setattr(openspec, "check", lambda root: (True, "all valid\n"))

    status = cli.cmd_check(argparse.Namespace(), run.inst)

    out = capsys.readouterr().out
    assert status != 0
    assert CYCLE in out
    assert out.index("all valid") < out.index(CYCLE)


def test_a_cycle_leaves_the_other_changes_and_their_messages_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Beside a real cycle: a `Needs:` on the change's own group, an `Independent:` group
    whose missing order edge is what would have closed a cycle, and a `Needs:` naming a
    change that does not exist add no cycle."""
    run = Replan(tmp_path, monkeypatch)
    two_changes_that_need_each_other(run)
    run.write(
        "own-group",
        f"# Tasks\n\n{OPT_OUT}\n"
        "## 1. [app] [tier1] One\n\n- [ ] 1.1 Test: it.\n- [ ] 1.2 Do it.\n\n"
        "## 2. [app] [tier1] Two\n\nNeeds: own-group group 1 — why\n\n"
        "- [ ] 2.1 Test: it.\n- [ ] 2.2 Do it.\n",
    )
    run.write(
        "independent",
        f"# Tasks\n\n{OPT_OUT}\n"
        "## 1. [app] [tier1] One\n\nNeeds: other-independent group 1 — why\n\n"
        "- [ ] 1.1 Test: it.\n- [ ] 1.2 Do it.\n\n"
        "## 2. [app] [tier1] Two\n\nIndependent: touches nothing in group 1\n\n"
        "- [ ] 2.1 Test: it.\n- [ ] 2.2 Do it.\n",
    )
    run.write("other-independent", tasks_md(1, needs={1: "independent group 2"}))
    run.write("missing-target", tasks_md(1, needs={1: "no-such-change group 1"}))

    status = cli.cmd_tags(argparse.Namespace(change=None, all=True), run.inst)

    lines = capsys.readouterr().out.splitlines()
    assert status == 1
    assert sum("Needs: cycle" in line for line in lines) == 2
    assert "own-group: 2 task group(s), all tagged" in lines
    assert "missing-target: 1 task group(s), all tagged" in lines
