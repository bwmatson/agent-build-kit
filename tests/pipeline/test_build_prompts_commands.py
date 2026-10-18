"""The six full build prompts carry the commands section once, and a continuation or a prompt
that runs no command does not (spec: build-prompts)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline import restack, stack_runner, wiring
from agent_build_kit.pipeline.agent_commands import commands_note
from tests.agent_command_fakes import repo_of
from tests.prompt_text import placeholders

SECTION = "Commands you may run"
FULL = ["TESTS_PROMPT", "IMPLEMENTATION_PROMPT", "REVIEW_FEEDBACK_PROMPT", "CHECKS_PROMPT"] + [
    "REWORK_PROMPT",
    "ADAPT_PROMPT",
]
CONTINUATIONS = [
    "IMPLEMENTATION_CONTINUATION",
    "CHECKS_CONTINUATION",
    "REVIEW_FEEDBACK_CONTINUATION",
    "REWORK_CONTINUATION",
    "ADAPT_CONTINUATION",
]


def python_note(tmp_path: Path) -> str:
    return commands_note(repo_of(tmp_path))


def render(template: str, commands: str) -> str:
    """The template filled with a word for each of its places but `commands`, which a template
    that has no such place ignores."""
    fields = {name: f"<{name}>" for name in placeholders(template)}
    return template.format(**{**fields, "commands": commands})


@pytest.mark.parametrize("name", FULL)
def test_a_full_prompt_carries_the_section_once_as_an_insertion(tmp_path: Path, name: str) -> None:
    template = getattr(stack_runner, name)
    note = python_note(tmp_path)

    with_note = render(template, note)
    without = render(template, "")

    assert note.startswith(SECTION)
    assert with_note.count(note) == 1
    assert with_note.count(SECTION) == 1
    assert with_note.replace(note, "") == without, "only an insertion"
    assert SECTION not in without


@pytest.mark.parametrize("name", CONTINUATIONS)
def test_a_continuation_does_not_carry_the_section(tmp_path: Path, name: str) -> None:
    note = python_note(tmp_path)
    assert note in render(stack_runner.TESTS_PROMPT, note), "the full prompt does"

    assert note not in render(getattr(stack_runner, name), note)


@pytest.mark.parametrize(
    "template", [wiring.COMMIT_FIX_PROMPT, restack.RESOLVE_PROMPT], ids=["commit-fix", "resolve"]
)
def test_a_prompt_that_runs_no_command_does_not_carry_the_section(
    tmp_path: Path, template: str
) -> None:
    note = python_note(tmp_path)
    assert note in render(stack_runner.TESTS_PROMPT, note), "the full prompt does"

    assert note not in render(template, note)
