"""Fixtures shared by the toolchain profiles' tests."""

from __future__ import annotations

import os
import shlex
import stat
from pathlib import Path

import pytest

from tests.node_stand_in import install_node_stand_in

# The tools the node profile's commands start besides `node`.
RECORDED_TOOLS = ("npm", "npx", "oxlint", "oxfmt", "tsc")


@pytest.fixture
def node_stand_ins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Programs named `node`, `npm`, `npx` and the node lint and type-check tools, ahead of
    everything else on `PATH`. Each appends its own name and then its arguments, one per line,
    to the returned file, which exists once some stand-in has been called; `node` also answers
    the profile's script probe from the `package.json` of the folder it runs in."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "args.log"
    for name in RECORDED_TOOLS:
        program = bin_dir / name
        program.write_text(
            f'#!/bin/sh\nprintf "%s\\n" "$(basename "$0")" "$@" >> {shlex.quote(str(log))}\n'
        )
        program.chmod(program.stat().st_mode | stat.S_IEXEC)
    install_node_stand_in(bin_dir)
    monkeypatch.setenv("NODE_STAND_IN_LOG", str(log))
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return log
