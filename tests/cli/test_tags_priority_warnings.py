"""`abk tags` and `abk check` warn of a group less urgent than a group that depends on it.

The warning is one line per edge, in the form of the other tag warnings, and changes no exit
status; `abk tags` also lists the priority a group will be promoted to and by which group
(spec: unit-scheduling).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit import openspec
from agent_build_kit.cli import pipeline as cli
from tests.cli.replan_driver import Replan
from tests.task_priority_files import group_md, groups_md

INVERTED = (
    "group 1 (priority 3) is needed by group 2 (priority 1): "
    "it will be promoted to 1; give it Priority 1 or lower group 2"
)


def warnings_of(out: str) -> list[str]:
    return [line for line in out.splitlines() if "is needed by group" in line]


def run_tags(run: Replan, capsys: pytest.CaptureFixture[str], **kw) -> tuple[int, str]:
    capsys.readouterr()
    status = cli.cmd_tags(
        argparse.Namespace(change=kw.get("change"), all=kw.get("all", False)), run.inst
    )
    return status, capsys.readouterr().out


def test_tags_prints_the_warning_beside_the_listing_and_exits_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch)
    run.write("feature", groups_md(group_md(1, 3), group_md(2, 1)))

    status, out = run_tags(run, capsys, change="feature")

    found = warnings_of(out)
    assert status == 0
    assert len(found) == 1
    assert found[0].endswith(f"warning: {INVERTED}")
    assert "tasks.md:line" in found[0]
    assert "feature: 2 task group(s), all tagged" in out


def test_tags_still_exits_one_for_a_change_with_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch)
    run.write(
        "feature",
        groups_md(group_md(1, 3), group_md(2, 1), group_md(3, 1).replace("[app]", "[nope]")),
    )

    status, out = run_tags(run, capsys, change="feature")

    assert status == 1
    assert len(warnings_of(out)) == 1
    assert "1 problem(s) in feature" in out


def test_check_prints_the_same_warnings_for_every_change_and_its_status_is_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch)
    run.write("feature", groups_md(group_md(1, 3), group_md(2, 1)))
    run.write("calm", groups_md(group_md(1, 3), group_md(2, 3)))
    monkeypatch.setattr(openspec, "check", lambda root: (True, "all valid\n"))

    capsys.readouterr()
    status = cli.cmd_check(argparse.Namespace(), run.inst)

    out = capsys.readouterr().out
    found = warnings_of(out)
    assert status == 0
    assert len(found) == 1
    assert INVERTED in found[0] and "feature" in found[0]
    assert out.index("all valid") < out.index(found[0])


def test_a_change_with_no_inversion_prints_no_priority_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch)
    run.write("calm", groups_md(group_md(1, 1), group_md(2, 1), group_md(3, 2)))
    run.write("feature", groups_md(group_md(1, 3), group_md(2, 1)))

    status, out = run_tags(run, capsys, all=True)

    assert status == 0
    assert [line for line in warnings_of(out) if "calm" in line] == []
    assert len(warnings_of(out)) == 1


def test_a_needs_line_warning_names_the_other_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch)
    run.write("other", groups_md(group_md(1, 3)))
    run.write("feature", groups_md(group_md(1, 1, needs="other group 1")))

    status, out = run_tags(run, capsys, change="feature")

    found = warnings_of(out)
    assert status == 0
    assert len(found) == 1
    assert "other" in found[0] and "group 1 (priority 3)" in found[0]


def test_the_listing_shows_the_promotion_of_a_group_and_a_plain_priority_for_the_rest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch)
    run.write("feature", groups_md(group_md(1, 3), group_md(2, 1)))
    run.write("calm", groups_md(group_md(1, 3), group_md(2, 3)))

    _, promoted = run_tags(run, capsys, change="feature")
    _, plain = run_tags(run, capsys, change="calm")

    assert "(priority 3, promoted to 1 by group 2)" in promoted
    assert "(priority 1)" in promoted
    assert plain.count("(priority 3)") == 2
    assert "promoted" not in plain


def test_the_listing_names_the_most_urgent_group_down_a_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch)
    run.write("feature", groups_md(group_md(1, 3), group_md(2, 3), group_md(3, 1)))

    _, out = run_tags(run, capsys, change="feature")

    assert out.count("(priority 3, promoted to 1 by group 3)") == 2
