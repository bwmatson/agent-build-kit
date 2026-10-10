"""The goal of a task group: the "Done when" sentence under its heading.

It is kept in the group's `goal` for the pull request description, and nothing
else the parser reads changes with it.
"""

from pathlib import Path

from agent_build_kit.pipeline.work_graph import TaskGroup, validate_tasks

OPT_OUT = "Acceptance: none — a fixture about goals\n"


def read(text: str, tmp_path: Path) -> list[TaskGroup]:
    (tmp_path / "tasks.md").write_text(f"# Tasks\n\n{OPT_OUT}\n{text}")
    groups, errors = validate_tasks(tmp_path / "tasks.md")
    assert errors == []
    return groups


def test_the_done_when_sentence_under_a_heading_is_the_goal(tmp_path: Path) -> None:
    groups = read(
        "## 1. [app] [tier1] Serve it\n\n"
        "Done when a loopback server answers the read endpoints.\n\n"
        "- [ ] 1.1 Test: it answers.\n- [ ] 1.2 Do it.\n",
        tmp_path,
    )

    assert [g.goal for g in groups] == ["Done when a loopback server answers the read endpoints."]


def test_a_goal_wrapped_over_lines_reads_as_one_sentence(tmp_path: Path) -> None:
    groups = read(
        "## 1. [app] [tier1] Serve it\n\n"
        "Done when a loopback server answers\n"
        "the read endpoints, and a host's limit still holds.\n\n"
        "- [ ] 1.1 Test: it answers.\n",
        tmp_path,
    )

    assert groups[0].goal == (
        "Done when a loopback server answers the read endpoints, and a host's limit still holds."
    )


def test_a_goal_after_a_needs_line_is_found_and_stops_at_the_first_task(tmp_path: Path) -> None:
    groups = read(
        "## 1. [app] [tier1] Serve it\n\n"
        "Needs: other-change group 2 merged — the server it calls\n\n"
        "Done when the answer is shown.\n"
        "- [ ] 1.1 Test: it shows.\n"
        "Done when this later line is a task's text, not the goal.\n",
        tmp_path,
    )

    assert groups[0].goal == "Done when the answer is shown."


def test_each_group_has_its_own_goal_and_one_without_has_none(tmp_path: Path) -> None:
    groups = read(
        "## 1. [app] [tier1] First\n\nDone when the first holds.\n\n- [ ] 1.1 Test: it.\n\n"
        "## 2. [app] [tier1] Second\n\n- [ ] 2.1 Test: it.\n\n"
        "## 3. [app] [tier1] Third\n\nDone when the third holds.\n\n- [ ] 3.1 Test: it.\n",
        tmp_path,
    )

    assert [g.goal for g in groups] == [
        "Done when the first holds.",
        "",
        "Done when the third holds.",
    ]


def test_a_paragraph_that_is_not_a_done_when_is_no_goal(tmp_path: Path) -> None:
    groups = read(
        "## 1. [app] [tier1] First\n\nSome context about the group.\n\n- [ ] 1.1 Test: it.\n",
        tmp_path,
    )

    assert groups[0].goal == ""


def test_the_tags_and_counts_are_read_as_before(tmp_path: Path) -> None:
    groups = read(
        "## 1. [app] [tier1] [narrow] Serve it\n\n"
        "Priority: 2\n\nDone when it serves.\n\n"
        "- [ ] 1.1 Test: it.\n- [ ] 1.2 Do it.\n",
        tmp_path,
    )

    (group,) = groups
    assert (group.number, group.repo, group.tier, group.flag) == (1, "app", "tier1", "narrow")
    assert (group.title, group.task_count, group.priority) == ("Serve it", 2, 2)
