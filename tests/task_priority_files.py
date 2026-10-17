"""Task files with `Priority:` lines, and the reading of them, shared by the priority tests."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.work_graph import TaskGroup, ValidationError, validate_tasks

OPT_OUT = "Acceptance: none — a fixture about priorities\n"


def tasks_md(*priorities: str | None, head: str = "") -> str:
    """A change with one group per entry, each carrying that `Priority:` value
    (none for a group without the line); `head` is written above the first group."""
    text = f"# Tasks\n\n{OPT_OUT}{head}\n"
    for number, value in enumerate(priorities, start=1):
        text += f"## {number}. [app] [unit-test] Group {number}\n\n"
        text += f"Priority: {value}\n\n" if value is not None else ""
        text += f"- [ ] {number}.1 Test: it.\n- [ ] {number}.2 Do it.\n\n"
    return text


def read(text: str, tmp_path: Path) -> tuple[list[TaskGroup], list[ValidationError]]:
    (tmp_path / "tasks.md").write_text(text)
    return validate_tasks(tmp_path / "tasks.md")


def priority_errors(errors: list[ValidationError]) -> list[int]:
    return [e.line for e in errors if "riority" in e.message]
