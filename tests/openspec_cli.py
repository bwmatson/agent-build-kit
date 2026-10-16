"""Telling a test that the OpenSpec CLI cannot be run from a test that failed.

`probe` asks the CLI for its version once; `require` passes a command's result through
and fails it when the status says the program was not found.
"""

from __future__ import annotations

import functools
import subprocess
import tempfile
from pathlib import Path

import pytest

from agent_build_kit import openspec

MESSAGE = "the OpenSpec CLI is not installed"
NOT_FOUND = 127
ERROR_LINES = 5
# Under the suite's per-test limit (tests/time_limit.py), so a stalled fetch is reported here.
PROBE_TIMEOUT = 45


def not_installed(status: object, stderr: str) -> str:
    tail = "\n".join(stderr.strip().splitlines()[-ERROR_LINES:])
    return f"{MESSAGE} (status {status}):\n{tail}".rstrip()


def probe(run: openspec.Run | None = None) -> None:
    with tempfile.TemporaryDirectory() as directory:
        runner = run or functools.partial(subprocess.run, timeout=PROBE_TIMEOUT)
        try:
            result = openspec.run(["--version"], cwd=Path(directory), run=runner)
        except subprocess.TimeoutExpired as error:
            stderr = error.stderr.decode() if isinstance(error.stderr, bytes) else error.stderr
            pytest.fail(not_installed("timeout", stderr or str(error)), pytrace=False)
        except OSError as error:
            pytest.fail(not_installed(type(error).__name__, str(error)), pytrace=False)
    if result.returncode != 0:
        pytest.fail(not_installed(result.returncode, result.stderr), pytrace=False)


def require(result: subprocess.CompletedProcess) -> subprocess.CompletedProcess:
    if result.returncode == NOT_FOUND:
        pytest.fail(not_installed(result.returncode, result.stderr), pytrace=False)
    return result
