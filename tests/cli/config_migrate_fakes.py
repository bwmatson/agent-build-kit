"""What `abk config --migrate` is driven with: an abk.yaml still on the old `limits` block, and
the person at the terminal (or nobody there)."""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

from agent_build_kit.cli import main
from tests.cli.policy_apply_fakes import Terminal

OLD = (
    "version: 1\n"
    "limits:\n"
    "  max_review_rounds: 3\n"
    "  # how many units at once\n"
    "  max_units_in_progress: 7  # busy\n"
    "  max_concurrent_stacks: 2\n"
)


class Person(Terminal):
    """A terminal that answers each question with the next of its answers."""

    def isatty(self) -> bool:
        return True


def write(directory: Path, text: str = OLD, name: str = "abk.yaml") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(text)
    return path


def run_migrate(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    path: Path,
    *argv: str,
    answers: tuple[str, ...] | None = (),
    piped: str = "",
) -> tuple[int, Person]:
    """`abk config --migrate <argv>` with `answers` at the terminal, or with no terminal when
    `answers` is None (stdin then holds `piped`): the exit code and the terminal (its `out`,
    `err`, `shown` and `asked`)."""
    terminal = Person(capsys, None, *(answers or ()))
    monkeypatch.setattr(sys, "stdin", terminal if answers is not None else io.StringIO(piped))
    code = main(["--config", str(path), "config", "--migrate", *argv])
    terminal.collect()
    return code, terminal


def beside(path: Path) -> list[str]:
    """Every file in the file's directory other than the file, sorted."""
    return sorted(entry.name for entry in path.parent.iterdir() if entry != path)
