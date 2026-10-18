"""`commands_note`: the "Commands you may run" section of a build prompt (spec: build-prompts)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import profiles
from agent_build_kit.pipeline.agent_commands import commands_note
from tests.agent_command_fakes import Silent, command, repo_of

HEADING = "Commands you may run"
BOUND = 600


def test_the_note_for_the_python_defaults_lists_the_four_commands(tmp_path: Path) -> None:
    note = commands_note(repo_of(tmp_path))

    assert note.startswith(HEADING)
    assert "refused" in note.splitlines()[0]
    assert "uv run pytest -q" in note
    assert "uv run pytest -q <path>" in note
    assert "uv run pre-commit run --all-files" in note
    assert "uv run pre-commit run --files <path>" in note
    assert "{path}" not in note
    assert len([line for line in note.splitlines() if line.startswith("- ")]) == 4


@pytest.mark.parametrize("name", ["python-uv", "node-npm"])
def test_the_note_of_each_built_in_profile_is_under_the_bound(tmp_path: Path, name: str) -> None:
    note = commands_note(repo_of(tmp_path, profile=name))

    assert note.startswith(HEADING)
    assert len(note) < BOUND


def test_a_node_repo_lists_its_own_commands(tmp_path: Path) -> None:
    note = commands_note(repo_of(tmp_path, profile="node-npm"))

    assert "npx vitest run\n" in note
    assert "npx vitest run <path>" in note
    assert "uv run" not in note


def test_a_repo_with_no_commands_has_an_empty_note(tmp_path: Path) -> None:
    assert commands_note(repo_of(tmp_path, agent_commands=[])) == ""
    with profiles.registered(Silent()):
        assert commands_note(repo_of(tmp_path, profile="fake-silent")) == ""


def test_the_note_follows_the_order_of_an_override(tmp_path: Path) -> None:
    note = commands_note(
        repo_of(
            tmp_path,
            agent_commands=[
                command("lint", "uv run ruff check ."),
                command("test", "uv run pytest -q"),
            ],
        )
    )

    assert note.index("uv run ruff check .") < note.index("uv run pytest -q")


def test_a_node_id_is_shown_as_a_test_id(tmp_path: Path) -> None:
    note = commands_note(
        repo_of(tmp_path, agent_commands=[command("test", "uv run pytest {path}", "node-id")])
    )

    assert "uv run pytest <test id>" in note
    assert "{path}" not in note


def many(count: int) -> list[str]:
    return [f"uv run tool-{n:02d} --option-with-a-long-name" for n in range(count)]


def test_commands_past_the_bound_are_listed_whole_in_order_and_the_rest_left_out(
    tmp_path: Path,
) -> None:
    lines = many(20)
    note = commands_note(
        repo_of(tmp_path, agent_commands=[command("test", line) for line in lines])
    )

    listed = [line for line in lines if line in note]
    assert 0 < len(listed) < len(lines)
    assert listed == lines[: len(listed)], "the leading ones, in order, none skipped"
    assert len(note) <= BOUND
    assert note.startswith(HEADING)
    assert "refused" in note.splitlines()[0]
    for entry in (e for e in note.splitlines() if e.startswith("- ")):
        assert any(entry.endswith(line) for line in lines), f"cut: {entry!r}"


def test_a_single_line_longer_than_the_bound_gives_an_empty_note(tmp_path: Path) -> None:
    long = "uv run tool " + "x" * (BOUND + 100)

    assert commands_note(repo_of(tmp_path, agent_commands=[command("test", long)])) == ""
