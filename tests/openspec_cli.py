"""Telling a test that the OpenSpec CLI cannot be run from a test that failed.

`probe` asks the CLI for its version once; `require` passes a command's result through
and fails it when the status says the program was not found.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import pytest

from agent_build_kit import openspec

MESSAGE = "the OpenSpec CLI is not installed"
NOT_FOUND = 127
ERROR_LINES = 5


def not_installed(status: object, stderr: str) -> str:
    tail = "\n".join(stderr.strip().splitlines()[-ERROR_LINES:])
    return f"{MESSAGE} (status {status}):\n{tail}".rstrip()


def probe(run: openspec.Run | None = None) -> None:
    with tempfile.TemporaryDirectory() as directory:
        try:
            result = openspec.run(["--version"], cwd=Path(directory), run=run)
        except OSError as error:
            pytest.fail(not_installed(type(error).__name__, str(error)), pytrace=False)
    if result.returncode != 0:
        pytest.fail(not_installed(result.returncode, result.stderr), pytrace=False)


def require(result: subprocess.CompletedProcess) -> subprocess.CompletedProcess:
    if result.returncode == NOT_FOUND:
        pytest.fail(not_installed(result.returncode, result.stderr), pytrace=False)
    return result
