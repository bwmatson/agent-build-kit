"""`abk tags` and `abk check` warn when a change's groups can give a unit unrelated parents.

The warning is one line per group, in the form of the other tag warnings, and changes no exit
code (spec: a-unit-waits-for-all-but-one-open-parent). Each test holds a shape that warns,
so none passes before the check exists; the silent shapes sit beside it.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit import openspec
from agent_build_kit.cli import pipeline as cli
from tests.cli.replan_driver import OPT_OUT, Replan


def group(number: int, repo: str = "app", *, flag: str = "", independent: bool = False) -> str:
    tier = "tier2" if flag == "acceptance" else "tier1"
    tags = f"[{repo}] [{tier}]" + (f" [{flag}]" if flag else "")
    text = f"## {number}. {tags} Group {number}\n\n"
    if independent:
        text += "Independent: it adds a receiver and needs nothing earlier\n\n"
    return text + f"- [ ] {number}.1 Test: it.\n- [ ] {number}.2 Do it.\n\n"


def tasks(*groups: str) -> str:
    return f"# Tasks\n\n{OPT_OUT}\n" + "".join(groups)


def acceptance_tasks(*groups: str) -> str:
    return "# Tasks\n\n" + "".join(groups)


def warnings_of(out: str) -> list[str]:
    return [line for line in out.splitlines() if "warning: group" in line]


def run_tags(run: Replan, capsys: pytest.CaptureFixture[str], **kw) -> tuple[int, str]:
    capsys.readouterr()
    status = cli.cmd_tags(
        argparse.Namespace(change=kw.get("change"), all=kw.get("all", False)), run.inst
    )
    return status, capsys.readouterr().out


def test_an_acceptance_group_after_an_independent_group_is_named_with_its_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch)
    run.write(
        "shape-acceptance",
        acceptance_tasks(group(1), group(2, independent=True), group(3, flag="acceptance")),
    )

    status, out = run_tags(run, capsys, change="shape-acceptance")

    found = warnings_of(out)
    assert status == 0
    assert len(found) == 1
    assert "tasks.md:line" in found[0]
    assert "group 3" in found[0]
    assert "acceptance" in found[0]
    assert "Independent" in found[0]


def test_a_narrow_group_after_an_independent_group_is_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch)
    run.write(
        "shape-narrow",
        tasks(group(1, flag="contract"), group(2, independent=True), group(3, flag="narrow")),
    )

    status, out = run_tags(run, capsys, change="shape-narrow")

    found = warnings_of(out)
    assert status == 0
    assert len(found) == 1
    assert "group 3" in found[0]
    assert "narrow" in found[0]


def test_an_independent_group_followed_by_a_later_group_names_the_later_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch)
    run.write("shape-later", tasks(group(1), group(2, independent=True), group(3)))

    status, out = run_tags(run, capsys, change="shape-later")

    found = warnings_of(out)
    assert status == 0
    assert len(found) == 1
    assert "group 3" in found[0]
    assert "Independent" in found[0]
    assert "shape-later: 3 task group(s), all tagged" in out


def test_a_needs_line_to_another_changes_group_beside_a_predecessor_is_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch)
    run.write("other-change", tasks(group(1)))
    needing = group(2).replace(
        "## 2. [app] [tier1] Group 2\n\n",
        "## 2. [app] [tier1] Group 2\n\nNeeds: other-change group 1 — it adds the hook\n\n",
    )
    run.write("shape-needs", tasks(group(1), needing))

    status, out = run_tags(run, capsys, change="shape-needs")

    found = warnings_of(out)
    assert status == 0
    assert len(found) == 1
    assert "group 2" in found[0]
    assert "Needs" in found[0]


def test_tags_all_warns_once_per_group_and_stays_silent_for_the_other_shapes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch)
    run.write("chain", tasks(group(1), group(2), group(3)))
    run.write("split-repos", tasks(group(1), group(2, "platform"), group(3, "platform")))
    run.write(
        "independent-elsewhere", tasks(group(1), group(2, "platform", independent=True), group(3))
    )
    run.write("warned", tasks(group(1), group(2, independent=True), group(3)))

    status, out = run_tags(run, capsys, all=True)

    found = warnings_of(out)
    assert status == 0
    assert len(found) == 1
    assert "warned" in found[0]
    assert "group 3" in found[0]


def test_check_prints_the_warning_after_the_openspec_output_and_exits_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch)
    run.write("warned", tasks(group(1), group(2, independent=True), group(3)))
    run.write("chain", tasks(group(1), group(2)))
    monkeypatch.setattr(openspec, "check", lambda root: (True, "all valid\n"))

    capsys.readouterr()
    status = cli.cmd_check(argparse.Namespace(), run.inst)

    out = capsys.readouterr().out
    found = warnings_of(out)
    assert status == 0
    assert len(found) == 1
    assert "group 3" in found[0]
    assert out.index("all valid") < out.index(found[0])


def test_the_warning_does_not_count_as_a_problem_when_a_real_problem_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch)
    run.write("warned", tasks(group(1), group(2, independent=True), group(3)))
    run.write("broken", "# Tasks\n\nnothing here\n")

    status, out = run_tags(run, capsys, all=True)

    assert status == 1
    assert len(warnings_of(out)) == 1
    assert "1 problem(s) in broken" in out
    assert "problem(s) in warned" not in out
