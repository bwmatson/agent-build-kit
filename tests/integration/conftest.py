"""Fixtures shared by the integration tests."""

from __future__ import annotations

import fcntl
import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.openspec_cli import probe

_WARM_SECONDS = 240


def _run_wide_npm(
    tmp_path_factory: pytest.TempPathFactory,
    name: str,
    overrides_for: Callable[[Path], dict[str, str]],
    warm: Callable[[Path, dict[str, str]], str],
) -> dict[str, str]:
    """Fetch one package into a run-wide npm cache once; return the npm overrides of the run.

    The folder belongs to one run: under workers it sits beside the workers' folders, and
    without them inside the base folder. The fetch is made under a lock shared by the workers
    when the folder's `ready` marker is missing. `warm` returns the empty string on success;
    a broken fetch has the cache removed and is made once more, and a second failure fails
    naming both messages.
    """
    basetemp = tmp_path_factory.getbasetemp()
    base = basetemp.parent if os.environ.get("PYTEST_XDIST_WORKER") else basetemp
    folder = base / name
    folder.mkdir(exist_ok=True)
    overrides = overrides_for(folder)
    with (folder / "lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        ready = folder / "ready"
        if not ready.exists():
            first = warm(folder, overrides)
            if first:
                shutil.rmtree(overrides["npm_config_cache"], ignore_errors=True)
                second = warm(folder, overrides)
                if second:
                    pytest.fail(
                        f"{name} could not be fetched and started through npx, twice:\n"
                        f"first:\n{first}\nsecond:\n{second}",
                        pytrace=False,
                    )
            ready.write_text("ready\n")
    return overrides


def _openspec_overrides(folder: Path) -> dict[str, str]:
    # An npm cache the environment already names is shared: CI's warm step fills it.
    cache = os.environ.get("npm_config_cache") or str(folder / "npm-cache")
    return {"npm_config_cache": cache, "npm_config_yes": "true"}


def _warm_openspec(folder: Path, overrides: dict[str, str]) -> str:
    """Probe the CLI through the run's npm cache; the empty string is success.

    The probe runs with a `HOME` inside the run's folder, never the real one, so none of the
    real user's npm configuration is read, as the tests (empty `HOME`) would not read it.
    """
    home = folder / "home"
    home.mkdir(exist_ok=True)
    try:
        probe(env={**overrides, "HOME": str(home)})
    except pytest.fail.Exception as error:
        return str(error)
    return ""


@pytest.fixture(scope="session")
def openspec_cache(tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    """The npm settings of the run's one OpenSpec CLI fetch, which the CLI is probed through.

    The suite gives each test an empty `HOME`, so without a shared npm cache every CLI call in
    a test would make `npx` fetch and install the package again. The run fetches it once into
    a run-wide cache (the one `npm_config_cache` names, when the environment sets it, so CI's
    warm step and the tests share one).
    """
    return _run_wide_npm(tmp_path_factory, "openspec", _openspec_overrides, _warm_openspec)


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


def _vitest_overrides(folder: Path) -> dict[str, str]:
    return {
        "npm_config_prefix": str(folder / "prefix"),
        "npm_config_cache": str(folder / "npm-cache"),
        "npm_config_yes": "true",
    }


@pytest.fixture(scope="session")
def vitest_env(tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    """The npm settings of the run's one Vitest fetch; a test merges them into its own environment.

    The suite gives each test an empty `HOME`, so a project with no `node_modules` makes `npx`
    fetch Vitest from the registry into that test's own `HOME` every time, and npm can finish
    such an install without an optional native binding, leaving Vitest unable to start. The run
    fetches Vitest once into a shared npm cache and checks it starts (see `_run_wide_npm`). The
    result holds only overrides, so a caller adds its own `HOME`: `{**os.environ, **vitest_env}`.
    """
    return _run_wide_npm(tmp_path_factory, "vitest", _vitest_overrides, _warm_vitest)
