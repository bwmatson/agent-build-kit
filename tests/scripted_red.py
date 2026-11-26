"""Test support: the Python profile with its lint and red commands replaced by scripted ones."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import profiles
from agent_build_kit.profiles.python_uv import PROFILE as PYTHON


def script_commands(
    monkeypatch: pytest.MonkeyPatch,
    *,
    clean_exit: int = 0,
    red_output: str,
    red_exit: int = 1,
    cwd_log: Path | None = None,
) -> None:
    """Make `profiles.get` hand out the Python profile with its clean command exiting
    `clean_exit` and its red command printing `red_output` and exiting `red_exit`. With `cwd_log`,
    the red command first appends the directory it runs in to that file."""

    class Scripted:
        """The Python profile with its two shell-outs replaced."""

        def clean_command(self, **_: object) -> str:
            return f"exit {clean_exit}"

        def red_command(self, files: list[str], ids: list[str] | None = None, **_: object) -> str:
            where = f"pwd >> {str(cwd_log)!r} && " if cwd_log else ""
            return f"{where}printf '%s' {red_output!r} && exit {red_exit}"

        def __getattr__(self, name):
            return getattr(PYTHON, name)

    monkeypatch.setattr(profiles, "get", lambda name: Scripted())
