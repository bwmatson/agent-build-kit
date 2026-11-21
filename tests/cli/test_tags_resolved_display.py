"""`abk tags`, `abk status` and `abk graph` show the project a group resolved to, and say it was
resolved (spec: project-resolution); the planner prompt does in its own test file."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit import openspec
from agent_build_kit.cli import pipeline as cli
from tests.cli.replan_driver import Replan
from tests.factories import new_unit
from tests.project_workspace import repos_declaring, tasks_editing

pytestmark = pytest.mark.usefixtures("scripted_engine")

TAGS = argparse.Namespace(change="feature", all=False)


def run_with(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *groups: tuple[str, str]) -> Replan:
    return Replan(
        tmp_path,
        monkeypatch,
        repos=repos_declaring(tmp_path / "planning", "app", ("web",)),
        feature=tasks_editing(*groups),
    )


def test_tags_shows_a_resolved_project_beside_the_repo_and_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = run_with(tmp_path, monkeypatch, ("[app] [unit-test] Add it", "web/src/a.ts"))

    status = cli.cmd_tags(TAGS, run.inst)

    line = next(line for line in capsys.readouterr().out.splitlines() if "Add it" in line)
    assert status == 0
    assert line.startswith("  1. [app/web] [unit-test] Add it")
    assert "(resolved)" in line


def test_tags_says_explicit_root_for_the_opt_out_and_nothing_for_an_unresolved_root_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = run_with(
        tmp_path,
        monkeypatch,
        ("[app/<root>] [unit-test] Stay", "web/src/a.ts"),
        ("[app] [unit-test] Mixed", "CHANGELOG.md"),
        ("[app/web] [unit-test] Written", "web/src/b.ts"),
    )

    status = cli.cmd_tags(TAGS, run.inst)

    lines = capsys.readouterr().out.splitlines()
    stay = next(line for line in lines if "Stay" in line)
    mixed = next(line for line in lines if "Mixed" in line)
    written = next(line for line in lines if "Written" in line)
    assert status == 0
    assert stay.startswith("  1. [app] [unit-test] Stay")
    assert "explicit root" in stay
    assert "resolved" not in mixed
    assert "explicit root" not in mixed
    assert "resolved" not in written


def test_status_reports_a_plan_stale_once_a_declared_project_moves_a_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("agent_build_kit.run_support.current_usage", lambda: None)
    run = run_with(tmp_path, monkeypatch, ("[app] [unit-test] Add it", "web/src/a.ts"))
    run.store.import_units([new_unit("feature/1", groups=(1,))])
    run.record("feature")

    capsys.readouterr()
    assert cli.cmd_status(argparse.Namespace(), run.inst) == 0

    lines = [line for line in capsys.readouterr().out.splitlines() if "stale" in line]
    assert any("feature" in line for line in lines)


def test_status_marks_a_unit_planned_from_a_resolved_group_and_not_one_written_for_the_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("agent_build_kit.run_support.current_usage", lambda: None)
    run = run_with(
        tmp_path,
        monkeypatch,
        ("[app] [unit-test] Resolved", "web/src/a.ts"),
        ("[app/web] [unit-test] Written", "web/src/b.ts"),
    )
    run.store.import_units(
        [
            new_unit("feature/1", groups=(1,), project="web"),
            new_unit("feature/2", groups=(2,), project="web"),
        ]
    )

    capsys.readouterr()
    assert cli.cmd_status(argparse.Namespace(), run.inst) == 0

    lines = capsys.readouterr().out.splitlines()
    heading = lines.index("projects set by resolution or an explicit root:")
    assert "feature/1" in lines[heading + 1] and "(resolved)" in lines[heading + 1]
    assert any("feature/1" in line and "(resolved)" in line for line in lines)
    assert not any("feature/2" in line and "resolved" in line for line in lines)


def node_line(page: str, unit_id: str) -> str:
    """The line of the graph page that draws the node of `unit_id`."""
    return next(line for line in page.splitlines() if f'["{unit_id}' in line)


def test_the_graph_marks_each_unit_by_its_own_group_and_keeps_the_subgraph_titles_bare(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = run_with(
        tmp_path,
        monkeypatch,
        ("[app] [unit-test] Resolved", "web/src/a.ts"),
        ("[app/web] [unit-test] Written", "web/src/b.ts"),
        ("[app/<root>] [unit-test] Opted out", "web/src/c.ts"),
        ("[app] [unit-test] Plain root", "CHANGELOG.md"),
    )
    run.store.import_units(
        [
            new_unit("feature/1", groups=(1,), project="web"),
            new_unit("feature/2", groups=(2,), project="web"),
            new_unit("feature/3", groups=(3,)),
            new_unit("feature/4", groups=(4,)),
        ]
    )

    assert cli.cmd_graph(argparse.Namespace(), run.inst) == 0

    page = run.inst.graph_page.read_text()
    assert 'subgraph app__project__web["web"]' in page
    assert "resolved" in node_line(page, "feature/1")
    assert "resolved" not in node_line(page, "feature/2")
    assert "explicit root" in node_line(page, "feature/3")
    assert "explicit root" not in node_line(page, "feature/4")


def declaring(*lines: str, heading: str = "[app] [unit-test] Move it") -> str:
    """A tasks.md with one group that carries `lines` and names source files."""
    return (
        "# Tasks\n\nAcceptance: none — a fixture\n\n"
        f"## 1. {heading}\n\n" + "".join(f"{line}\n" for line in lines) + "\n"
        "- [ ] 1.1 Move `src/app/old.py` to `src/app/new.py`.\n"
    )


def test_tags_shows_the_declared_mode_beside_the_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(
        tmp_path, monkeypatch, feature=declaring("Mode: refactor — moves and renames only")
    )

    status = cli.cmd_tags(TAGS, run.inst)

    line = next(line for line in capsys.readouterr().out.splitlines() if "Move it" in line)
    assert status == 0
    assert "declared refactor" in line


@pytest.mark.parametrize(
    ("lines", "heading"),
    [
        (("Mode: refactor",), "[app] [unit-test] Move it"),
        (("Mode: tests_only — nothing else",), "[app] [unit-test] Move it"),
        (("Mode: refactor — moves only",), "[app] [e2e-test] Move it"),
        (("Mode: refactor — moves only", "- [ ] 1.2 Test: it moved."), "[app] [unit-test] Move it"),
        (
            ("Mode: refactor — moves only", "Tests: required — risky"),
            "[app] [unit-test] Move it",
        ),
    ],
    ids=["no reason", "other value", "e2e group", "Test: task", "Tests: required"],
)
def test_tags_exits_1_on_a_declared_mode_the_group_cannot_have(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    lines: tuple[str, ...],
    heading: str,
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=declaring(*lines, heading=heading))

    status = cli.cmd_tags(TAGS, run.inst)

    assert status == 1
    assert "Mode:" in capsys.readouterr().out


def tags_mode_warnings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], text: str
) -> tuple[int, list[str]]:
    """The status of `abk tags` over `text` and the warnings it printed that name `Mode:`."""
    run = Replan(tmp_path, monkeypatch, feature=text)
    status = cli.cmd_tags(TAGS, run.inst)
    lines = capsys.readouterr().out.splitlines()
    return status, [line for line in lines if line.startswith("warning") and "Mode:" in line]


MOVES = (
    "# Tasks\n\nAcceptance: none — a fixture\n\n## 1. [app] [unit-test] Tidy the package\n\n"
    "{preface}"
    "- [ ] 1.1 Move `src/pkg/old_name.py` to `src/pkg/new_name.py`.\n"
    "- [ ] 1.2 Rename `scripts/build_a.py` to `scripts/make_a.py`.\n"
    "- [ ] 1.3 Edit `src/pkg/__init__.py` to follow the move.\n"
    "{extra}"
)


def test_tags_warns_of_a_group_that_reads_as_a_reorganization_and_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    text = MOVES.format(preface="", extra="")

    status, warnings = tags_mode_warnings(tmp_path, monkeypatch, capsys, text)

    assert status == 0
    assert len(warnings) == 1
    assert "group 1" in warnings[0]
    assert "Mode: refactor — <reason>" in warnings[0]
    assert "`Test:` task" in warnings[0]


@pytest.mark.parametrize(
    ("task", "warned"),
    [
        ("Renames `src/pkg/a.py` to `src/pkg/b.py`.", 1),
        ("Moving `src/pkg/a.py` to `src/pkg/b.py`.", 1),
        ("Run `git mv src/pkg/a.py src/pkg/b.py`.", 1),
        ("Remove `src/pkg/a.py`.", 0),
        ("Add a movement helper in `src/pkg/a.py`.", 0),
    ],
    ids=["Renames", "Moving", "git mv", "Remove", "movement"],
)
def test_tags_warns_of_a_group_by_how_its_task_words_a_move(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    task: str,
    warned: int,
) -> None:
    text = (
        "# Tasks\n\nAcceptance: none — a fixture\n\n## 1. [app] [unit-test] Tidy the package\n\n"
        f"- [ ] 1.1 {task}\n"
    )

    status, warnings = tags_mode_warnings(tmp_path, monkeypatch, capsys, text)

    assert status == 0
    assert len(warnings) == warned


@pytest.mark.parametrize(
    ("preface", "extra"),
    [
        ("", "- [ ] 1.4 Test: the new path imports.\n"),
        ("Tests: required — the move changes an import\n\n", ""),
        ("Mode: refactor — moves only\n\n", ""),
        ("", "- [ ] 1.4 Add a new test file `tests/test_new.py` for the moved module.\n"),
    ],
    ids=["a Test: task", "Tests: required", "a Mode: line", "a new test file"],
)
def test_tags_does_not_warn_of_a_reorganization_group_that_has_a_way_out_already(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    preface: str,
    extra: str,
) -> None:
    _, bare = tags_mode_warnings(
        tmp_path / "bare", monkeypatch, capsys, MOVES.format(preface="", extra="")
    )
    text = MOVES.format(preface=preface, extra=extra)

    status, warnings = tags_mode_warnings(tmp_path / "exit", monkeypatch, capsys, text)

    assert len(bare) == 1
    assert status == 0
    assert warnings == []


NOTHING_TO_WRITE = "the tests step has nothing to write"


def nothing_to_write(out: str) -> list[str]:
    return [line for line in out.splitlines() if NOTHING_TO_WRITE in line]


def test_tags_warns_of_a_tests_first_group_with_no_test_task_names_the_ways_out_and_exits_0(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=declaring())

    status = cli.cmd_tags(TAGS, run.inst)

    found = nothing_to_write(capsys.readouterr().out)
    assert status == 0
    assert len(found) == 1
    assert "group 1" in found[0]
    assert "Test:" in found[0]
    assert "Tests: required" in found[0]
    assert "Mode: refactor" in found[0]


@pytest.mark.parametrize(
    "lines",
    [
        ("- [ ] 1.2 Test: it moved.",),
        ("Tests: required — the move is risky",),
        ("Mode: refactor — moves and renames only",),
    ],
    ids=["Test: task", "Tests: required", "Mode: refactor"],
)
def test_tags_warns_only_of_the_group_with_no_way_out(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    lines: tuple[str, ...],
) -> None:
    second = (
        "## 2. [app] [unit-test] Move that\n\n- [ ] 2.1 Move `src/app/a.py` to `src/app/b.py`.\n"
    )
    run = Replan(tmp_path, monkeypatch, feature=declaring(*lines) + second)

    status = cli.cmd_tags(TAGS, run.inst)

    found = nothing_to_write(capsys.readouterr().out)
    assert status == 0
    assert len(found) == 1
    assert "group 2" in found[0]


def test_check_prints_the_same_warning_and_the_count_of_groups_it_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=declaring())
    run.write("other", declaring(heading="[app] [unit-test] Move that"))
    run.write("fine", declaring("- [ ] 1.2 Test: it moved."))
    monkeypatch.setattr(openspec, "check", lambda root: (True, "all valid\n"))

    capsys.readouterr()
    status = cli.cmd_check(argparse.Namespace(), run.inst)

    out = capsys.readouterr().out
    assert status == 0
    assert len(nothing_to_write(out)) == 2, out
    assert any("2 group" in line and "no test task" in line for line in out.splitlines()), out
