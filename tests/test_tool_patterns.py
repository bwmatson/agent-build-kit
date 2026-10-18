"""The `Bash(...)` pattern matcher lives where it needs no protocol library (spec:
toolchain-profiles)."""

from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest

from agent_build_kit.runtimes import acp
from agent_build_kit.tool_patterns import allows

LIST = "Read Bash(git *) Bash(uv run *)"


def test_a_pattern_covers_a_line_it_matches() -> None:
    assert allows("Bash(uv run *)", "uv run pytest -q")


@pytest.mark.parametrize(
    "line",
    [
        "uv run pytest -q; echo $?",
        "uv run pytest -q | tee x",
        "python -m pytest tests -q",
        "ruff check .",
    ],
)
def test_a_line_that_chains_or_is_not_covered_is_refused(line: str) -> None:
    assert allows("Bash(uv run *)", "uv run pytest -q")
    assert not allows("Bash(uv run *)", line)


def test_a_bare_bash_entry_allows_any_single_command() -> None:
    assert allows("Read Bash", "ruff check .")
    assert not allows("Read Bash", "ruff check . && ls")


def test_a_pattern_among_other_entries_is_found() -> None:
    assert allows(LIST, "uv run pytest -q")
    assert not allows(LIST, "ruff check .")


def test_the_module_works_with_the_protocol_library_blocked() -> None:
    script = textwrap.dedent(
        """
        import sys
        sys.modules["acp"] = None
        from agent_build_kit.tool_patterns import allows
        assert allows("Bash(uv run *)", "uv run pytest -q")
        assert not allows("Bash(uv run *)", "ruff check .")
        """
    )

    done = subprocess.run([sys.executable, "-I", "-c", script], capture_output=True, text=True)

    assert done.returncode == 0, done.stderr


def test_the_acp_runtime_uses_the_same_function() -> None:
    assert acp.allows is allows
