"""Test support: the Python profile with its lint and red commands replaced by scripted ones."""

from __future__ import annotations

import shlex
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
    head_log: Path | None = None,
) -> None:
    """Make `profiles.get` hand out the Python profile with its clean command exiting
    `clean_exit` and its red command printing `red_output` and exiting `red_exit`. With `cwd_log`,
    the red command first appends the directory it runs in to that file; with `head_log`, the
    commit that directory holds."""

    class Scripted:
        """The Python profile with its two shell-outs replaced."""

        def clean_command(self, **_: object) -> str:
            return f"exit {clean_exit}"

        def red_command(self, files: list[str], ids: list[str] | None = None, **_: object) -> str:
            where = f"pwd >> {shlex.quote(str(cwd_log))} && " if cwd_log else ""
            if head_log:
                where += f"git rev-parse HEAD >> {shlex.quote(str(head_log))} && "
            return f"{where}printf '%s' {shlex.quote(red_output)} && exit {red_exit}"

        def __getattr__(self, name):
            return getattr(PYTHON, name)

    monkeypatch.setattr(profiles, "get", lambda name: Scripted())
