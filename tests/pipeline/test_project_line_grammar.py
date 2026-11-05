"""A group's `Project:` line: `add <path> <profile>`, `remove <path>` and `replace <old> with <new>
<profile>`, for the heading's repository, read and validated; `abk tags` shows each as pending or
applied (spec: project-lines)."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.units import ProjectLine
from agent_build_kit.pipeline.work_graph import TaskGroup, ValidationError, validate_tasks
from tests.project_workspace import OPT_OUT, app_with_projects

GRAMMAR = "Project: add <path> <profile>"


def tasks_text(*groups: tuple[str, tuple[str, ...]], head: str = "") -> str:
    """A `tasks.md` whose groups are each a heading (the text after `## <n>. `) and the lines
    under it."""
    text = f"# Tasks\n\n{OPT_OUT}{head}\n"
    for number, (heading, body) in enumerate(groups, start=1):
        lines = "".join(f"{line}\n" for line in body)
        text += f"## {number}. {heading}\n\n{lines}\n- [ ] {number}.1 Test: it.\n\n"
    return text


def read(
    tmp_path: Path,
    *groups: tuple[str, tuple[str, ...]],
    declared: tuple[str, ...] = (),
    profiles: dict[str, str] | None = None,
    head: str = "",
) -> tuple[list[TaskGroup], list[ValidationError]]:
    """`validate_tasks` over `groups` for a repo `app` that declares `declared` beside its root,
    each with the profile `profiles` names (`python-uv` when it names none)."""
    (tmp_path / "tasks.md").write_text(tasks_text(*groups, head=head))
    return validate_tasks(
        tmp_path / "tasks.md",
        repos=("app",),
        projects={"app": declared},
        splits={"app": ("rest",)},
        project_profiles={
            "app": {path: (profiles or {}).get(path, "python-uv") for path in declared}
        },
    )


def one(*lines: str, heading: str = "[app] [unit-test] Group 1") -> tuple[str, tuple[str, ...]]:
    return heading, lines


def line_of(tmp_path: Path, needle: str) -> int:
    text = (tmp_path / "tasks.md").read_text().splitlines()
    return next(n for n, line in enumerate(text, start=1) if needle in line)


def test_the_three_forms_are_read_with_their_fields(tmp_path: Path) -> None:
    groups, errors = read(
        tmp_path,
        one(
            "Project: add conformance python-uv",
            "Project: remove old",
            "Project: replace host with member python-uv",
        ),
        declared=("old", "host"),
    )

    assert errors == []
    assert groups[0].project_lines == (
        ProjectLine(
            action="add", path="conformance", profile="python-uv", line=line_of(tmp_path, "add")
        ),
        ProjectLine(action="remove", path="old", line=line_of(tmp_path, "remove old")),
        ProjectLine(
            action="replace",
            path="host",
            new_path="member",
            profile="python-uv",
            line=line_of(tmp_path, "replace"),
        ),
    )


def test_the_keyword_and_the_verb_are_read_in_any_case(tmp_path: Path) -> None:
    groups, errors = read(
        tmp_path,
        one("project: ADD conformance node-npm", "PROJECT: Remove old"),
        declared=("old",),
    )

    assert errors == []
    assert [(p.action, p.path) for p in groups[0].project_lines] == [
        ("add", "conformance"),
        ("remove", "old"),
    ]


def test_several_groups_each_keep_their_own_lines(tmp_path: Path) -> None:
    groups, errors = read(
        tmp_path,
        one("Project: add one python-uv"),
        one("Project: add two python-uv", heading="[app] [unit-test] Group 2"),
    )

    assert errors == []
    assert [[p.path for p in g.project_lines] for g in groups] == [["one"], ["two"]]


@pytest.mark.parametrize("written", ["./web/", "web/", "./web"])
def test_a_path_is_normalised_as_project_init_does(tmp_path: Path, written: str) -> None:
    groups, errors = read(tmp_path, one(f"Project: add {written} python-uv"))

    assert errors == []
    assert groups[0].project_lines[0].path == "web"


@pytest.mark.parametrize(
    "written",
    [
        "Project: add conformance",
        "Project: add",
        "Project: remove",
        "Project: remove one two",
        "Project: replace old new python-uv",
        "Project: replace old with new",
        "Project: rename old new",
        "Project:",
    ],
)
def test_a_malformed_line_is_reported_at_its_line_with_the_grammar(
    tmp_path: Path, written: str
) -> None:
    groups, errors = read(tmp_path, one(written), declared=("old",))

    assert [e.line for e in errors] == [line_of(tmp_path, written)]
    assert GRAMMAR in errors[0].message
    assert groups[0].project_lines == ()


def test_a_line_above_the_first_group_is_reported(tmp_path: Path) -> None:
    _, errors = read(tmp_path, one(), head="Project: add web python-uv\n")

    assert [e.line for e in errors] == [line_of(tmp_path, "Project:")]
    assert "group" in errors[0].message


def test_a_line_in_a_group_whose_heading_cannot_be_read_is_reported(tmp_path: Path) -> None:
    groups, errors = read(
        tmp_path,
        one("Project: add web python-uv", heading="[nowhere] [unit-test] Group 1"),
    )

    assert line_of(tmp_path, "Project:") in [e.line for e in errors]
    assert any("heading" in e.message and "Project:" in e.message for e in errors)
    assert groups == []


def test_an_unregistered_profile_is_reported_naming_it(tmp_path: Path) -> None:
    groups, errors = read(
        tmp_path,
        one("Project: add web nope", "Project: replace old with new nope"),
        declared=("old",),
    )

    assert [e.line for e in errors] == [
        line_of(tmp_path, "add web"),
        line_of(tmp_path, "replace"),
    ]
    assert all("nope" in e.message and "python-uv" in e.message for e in errors)
    assert groups[0].project_lines == ()


@pytest.mark.parametrize(
    "written",
    [
        "Project: add ../escape python-uv",
        "Project: add a/../../escape python-uv",
        "Project: remove ../escape",
        "Project: replace old with ../escape python-uv",
        "Project: add /elsewhere/escape python-uv",
    ],
)
def test_a_path_outside_the_repository_is_reported(tmp_path: Path, written: str) -> None:
    groups, errors = read(tmp_path, one(written), declared=("old",))

    assert [e.line for e in errors] == [line_of(tmp_path, written)]
    assert "inside the repo" in errors[0].message
    assert groups[0].project_lines == ()


def test_a_later_group_may_tag_a_project_an_earlier_group_adds(tmp_path: Path) -> None:
    groups, errors = read(
        tmp_path,
        one("Project: add conformance python-uv"),
        one(heading="[app/conformance] [unit-test] Group 2"),
    )

    assert errors == []
    assert [(g.repo, g.project) for g in groups] == [("app", "."), ("app", "conformance")]


def test_a_later_group_may_tag_a_project_an_earlier_group_replaces_into(tmp_path: Path) -> None:
    groups, errors = read(
        tmp_path,
        one("Project: replace host with member python-uv"),
        one(heading="[app/member] [unit-test] Group 2"),
        declared=("host",),
    )

    assert errors == []
    assert groups[1].project == "member"


def test_a_project_no_group_of_the_change_adds_is_still_unknown(tmp_path: Path) -> None:
    _, errors = read(
        tmp_path,
        one("Project: add conformance python-uv"),
        one(heading="[app/other] [unit-test] Group 2"),
    )

    assert [e.line for e in errors] == [line_of(tmp_path, "[app/other]")]
    assert "unknown project" in errors[0].message


def test_an_add_already_listed_with_that_profile_is_valid(tmp_path: Path) -> None:
    groups, errors = read(
        tmp_path,
        one("Project: add web node-npm"),
        declared=("web",),
        profiles={"web": "node-npm"},
    )

    assert errors == []
    assert [p.path for p in groups[0].project_lines] == ["web"]


def test_a_remove_of_a_path_not_listed_is_valid(tmp_path: Path) -> None:
    groups, errors = read(tmp_path, one("Project: remove gone"))

    assert errors == []
    assert [(p.action, p.path) for p in groups[0].project_lines] == [("remove", "gone")]


def test_an_add_listed_with_another_profile_is_reported(tmp_path: Path) -> None:
    groups, errors = read(
        tmp_path,
        one("Project: add web node-npm"),
        declared=("web",),
        profiles={"web": "python-uv"},
    )

    assert [e.line for e in errors] == [line_of(tmp_path, "Project:")]
    assert "python-uv" in errors[0].message and "node-npm" in errors[0].message
    assert groups[0].project_lines == ()


@pytest.mark.parametrize(
    "written", ["Project: remove old", "Project: replace old with new python-uv"]
)
def test_removing_a_project_a_later_group_tags_is_reported(tmp_path: Path, written: str) -> None:
    _, errors = read(
        tmp_path,
        one(written),
        one(heading="[app/old] [unit-test] Group 2"),
        declared=("old",),
    )

    assert [e.line for e in errors] == [line_of(tmp_path, "Project:")]
    assert "still used" in errors[0].message and "old" in errors[0].message


def test_removing_a_project_an_earlier_group_tags_is_valid(tmp_path: Path) -> None:
    groups, errors = read(
        tmp_path,
        one(heading="[app/old] [unit-test] Group 1"),
        one("Project: remove old", heading="[app] [unit-test] Group 2"),
        declared=("old",),
    )

    assert errors == []
    assert [p.path for p in groups[1].project_lines] == ["old"]


def test_abk_tags_shows_each_line_as_pending_or_applied(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = app_with_projects(tmp_path, "web")
    directory = inst.changes_dir / "feature"
    directory.mkdir(parents=True)
    (directory / "tasks.md").write_text(
        tasks_text(
            one(
                "Project: add web python-uv",
                "Project: add extra python-uv",
                "Project: remove gone",
                "Project: remove web",
            )
        )
    )

    status = cli.cmd_tags(argparse.Namespace(change="feature", all=False), inst)

    shown = capsys.readouterr().out.splitlines()
    assert status == 0

    def shown_for(needle: str) -> str:
        return next(line for line in shown if needle in line)

    assert "applied" in shown_for("add web")
    assert "pending" in shown_for("add extra")
    assert "applied" in shown_for("remove gone")
    assert "pending" in shown_for("remove web")
