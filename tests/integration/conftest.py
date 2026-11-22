"""Fixtures shared by the integration tests."""

from __future__ import annotations

import fcntl
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.openspec_cli import probe

_INSTALL_SECONDS = 240
_CHECK_SECONDS = 120


@pytest.fixture(scope="session")
def openspec_cli() -> None:
    """The OpenSpec CLI starts, asked once; a test that runs it requests this."""
    probe()


def _install_vitest(folder: Path, env: dict[str, str]) -> str:
    """Install Vitest into the run's prefix and start it once; the empty string is success."""
    install = subprocess.run(
        ["npm", "install", "--global", "--no-audit", "--no-fund", "vitest"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=_INSTALL_SECONDS,
    )
    project = folder / "check-project"
    shutil.rmtree(project, ignore_errors=True)
    project.mkdir()
    (project / "package.json").write_text('{"name": "check", "type": "module"}\n')
    (project / "a.test.ts").write_text(
        "import { expect, test } from 'vitest';\ntest('t', () => { expect(1).toBe(1); });\n"
    )
    check = subprocess.run(
        ["npx", "vitest", "run", "--passWithNoTests"],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=_CHECK_SECONDS,
    )
    if install.returncode == 0 and check.returncode == 0:
        return ""
    return (
        f"npm install exit {install.returncode}:\n{install.stdout}{install.stderr}\n"
        f"vitest check exit {check.returncode}:\n{check.stdout}{check.stderr}"
    )


@pytest.fixture(scope="session")
def vitest_env(tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    """The environment of the run's one Vitest install, for a test that runs `npx vitest`.

    The suite gives each test an empty `HOME`, so a project with no `node_modules` makes `npx`
    fetch Vitest from the registry into that test's own `HOME` every time, and npm can finish
    such an install without an optional native binding, leaving Vitest unable to start. The run
    installs Vitest once, under a lock shared by the workers, checks it starts, and every test
    that needs it takes this environment.
    """
    folder = tmp_path_factory.getbasetemp().parent / "vitest"
    folder.mkdir(exist_ok=True)
    env = {
        **os.environ,
        "npm_config_prefix": str(folder / "prefix"),
        "npm_config_cache": str(folder / "npm-cache"),
        "npm_config_yes": "true",
    }
    with (folder / "lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        ready = folder / "ready"
        if not ready.exists():
            first = _install_vitest(folder, env)
            if first:
                shutil.rmtree(folder / "prefix", ignore_errors=True)
                shutil.rmtree(folder / "npm-cache", ignore_errors=True)
                second = _install_vitest(folder, env)
                if second:
                    pytest.fail(
                        "an incomplete npm install of Vitest, twice:\n"
                        f"first:\n{first}\nsecond:\n{second}"
                    )
            ready.write_text("ready\n")
    return env
