"""Adding a runtime to or removing it from `tests.runtimes_blocked` and `tests.runtimes_allowed`
in `abk.yaml` by editing the file as text, so every comment and every other line stays."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.model import Frozen

__all__ = ["ConfigTextEditError", "TextEdit", "add_runtime", "remove_runtime"]


class ConfigTextEditError(ValueError):
    """The file cannot be changed as text; the message gives the reason and nothing was
    written, backup included."""


class TextEdit(Frozen):
    """What an edit did."""

    changed: bool = False
    # The backup this edit made; None when one already existed or nothing was written.
    backup: Path | None = None
    # One line saying what was done, or why nothing was.
    summary: str = ""


def add_runtime(path: Path, setting: str, name: str) -> TextEdit:
    raise NotImplementedError


def remove_runtime(path: Path, setting: str, name: str) -> TextEdit:
    raise NotImplementedError
