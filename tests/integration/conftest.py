"""Fixtures shared by the integration tests."""

from __future__ import annotations

import fcntl
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.openspec_cli import probe

_WARM_SECONDS = 240


@pytest.fixture(scope="session")
def openspec_cache(tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    """The npm settings of the run's one OpenSpec CLI fetch, which the CLI is probed through.

    The suite gives each test an empty `HOME`, so without a shared npm cache every CLI call in
    a test would make `npx` fetch and install the package again. The run fetches it once into
    a run-wide cache, under a lock the workers share; a broken fetch is removed and made once
    more. Under workers the folder sits beside the workers' folders, else inside the base folder.
    """
    basetemp = tmp_path_factory.getbasetemp()
    base = basetemp.parent if os.environ.get("PYTEST_XDIST_WORKER") else basetemp
    folder = base / "openspec"
    folder.mkdir(exist_ok=True)
    overrides = {"npm_config_cache": str(folder / "npm-cache"), "npm_config_yes": "true"}
    with (folder / "lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        ready = folder / "ready"
        if not ready.exists():
            try:
                probe(env=overrides)
            except pytest.fail.Exception:
                shutil.rmtree(folder / "npm-cache", ignore_errors=True)
                probe(env=overrides)
            ready.write_text("ready\n")
    return overrides


@pytest.fixture
def openspec_cli(openspec_cache: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    """The OpenSpec CLI starts from the run's warm npm cache; a test that runs it requests this."""
    for key, value in openspec_cache.items():
        monkeypatch.setenv(key, value)


def _warm_vitest(folder: Path, overrides: dict[str, str]) -> str:
    """Fetch Vitest into the run's npm cache and start it once; the empty string is success.

    The child runs with a `HOME` inside the run's folder, never the real one, so none of
    the real user's npm configuration is read. `npx` is used instead of a global install, so
    nothing reaches a toolchain manager's own tool folder.
    """
    home = folder / "home"
    home.mkdir(exist_ok=True)
    env = {**os.environ, **overrides, "HOME": str(home)}
    project = folder / "check-project"
    shutil.rmtree(project, ignore_errors=True)
    project.mkdir()
    (project / "package.json").write_text('{"name": "check", "type": "module"}\n')
    (project / "a.test.ts").write_text(
        "import { expect, test } from 'vitest';\ntest('t', () => { expect(1).toBe(1); });\n"
    )
    try:
        done = subprocess.run(
            ["npx", "--yes", "vitest", "run", "--passWithNoTests"],
            cwd=project,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=_WARM_SECONDS,
        )
    except subprocess.TimeoutExpired as error:
        return f"timed out after {_WARM_SECONDS} s: {error.stderr or error}"
    except OSError as error:
        return f"npx could not be run ({type(error).__name__}): {error}"
    if done.returncode == 0:
        return ""
    return f"vitest exit {done.returncode}:\n{done.stdout}{done.stderr}"


@pytest.fixture(scope="session")
def vitest_env(tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    """The npm settings of the run's one Vitest fetch; a test merges them into its own environment.

    The suite gives each test an empty `HOME`, so a project with no `node_modules` makes `npx`
    fetch Vitest from the registry into that test's own `HOME` every time, and npm can finish
    such an install without an optional native binding, leaving Vitest unable to start. The run
    fetches Vitest once into a shared npm cache, under a lock shared by the workers, and checks
    it starts; a broken fetch is removed and made once more. The result holds only overrides, so
    a caller adds its own `HOME`: `{**os.environ, **vitest_env}`. The folder belongs to one run:
    under workers it sits beside the workers' folders, and without them inside the base folder.
    """
    basetemp = tmp_path_factory.getbasetemp()
    base = basetemp.parent if os.environ.get("PYTEST_XDIST_WORKER") else basetemp
    folder = base / "vitest"
    folder.mkdir(exist_ok=True)
    overrides = {
        "npm_config_prefix": str(folder / "prefix"),
        "npm_config_cache": str(folder / "npm-cache"),
        "npm_config_yes": "true",
    }
    with (folder / "lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        ready = folder / "ready"
        if not ready.exists():
            first = _warm_vitest(folder, overrides)
            if first:
                shutil.rmtree(folder / "npm-cache", ignore_errors=True)
                second = _warm_vitest(folder, overrides)
                if second:
                    pytest.fail(
                        "Vitest could not be fetched and started through npx, twice:\n"
                        f"first:\n{first}\nsecond:\n{second}",
                        pytrace=False,
                    )
            ready.write_text("ready\n")
    return overrides
