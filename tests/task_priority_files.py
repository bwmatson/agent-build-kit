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


def group_md(
    number: int,
    priority: int,
    *,
    flag: str = "",
    independent: bool = False,
    needs: str = "",
) -> str:
    """One `## N.` group at that `Priority:`; `needs` is the target of a `Needs:` line."""
    kind = "e2e-test" if flag == "acceptance" else "unit-test"
    tags = f"[app] [{kind}]" + (f" [{flag}]" if flag else "")
    text = f"## {number}. {tags} Group {number}\n\nPriority: {priority}\n"
    if independent:
        text += "Independent: it adds a receiver and needs nothing earlier\n"
    if needs:
        text += f"Needs: {needs} — a reason\n"
    return text + f"\n- [ ] {number}.1 Test: it.\n- [ ] {number}.2 Do it.\n\n"


def groups_md(*groups: str) -> str:
    """A change made of `group_md` groups; it opts out of an acceptance group unless it has one."""
    body = "".join(groups)
    return "# Tasks\n\n" + ("" if "[acceptance]" in body else f"{OPT_OUT}\n") + body
