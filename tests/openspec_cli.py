"""Telling a test that the OpenSpec CLI cannot be run from a test that failed.

`probe` asks the CLI for its version once; `require` passes a command's result through
and fails it when the status says the program was not found.
"""

from __future__ import annotations

import subprocess

from agent_build_kit import openspec

MESSAGE = "the OpenSpec CLI is not installed"


def probe(run: openspec.Run | None = None) -> None:
    raise NotImplementedError


def require(result: subprocess.CompletedProcess) -> subprocess.CompletedProcess:
    raise NotImplementedError
