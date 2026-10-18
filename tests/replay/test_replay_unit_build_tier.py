"""The build the acceptance test runs in its own session is an e2e test there, so it is held to
the e2e time limit and not the 60-second default, which a real build overruns.

Collected under the command the driver runs, so a change to that command that stops the build
being selected, or a marker the time-limit plugin does not see, fails here."""

from __future__ import annotations

import subprocess
from pathlib import Path

from tests.integration import replay_unit_build as build

BUILD_ID = "replay_unit_build.py::test_the_unit_is_built"


def collect(basetemp: Path, *extra: str) -> str:
    done = subprocess.run(
        [*build.session_argv(basetemp), "--collect-only", "-q", *extra],
        cwd=build.REPO,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return done.stdout + done.stderr


def test_the_build_is_collected_under_the_drivers_command(tmp_path: Path) -> None:
    assert BUILD_ID in collect(tmp_path)


def test_the_build_collected_that_way_carries_the_e2e_marker(tmp_path: Path) -> None:
    # `-m` selects by the marks the time-limit plugin's `get_closest_marker` reads.
    assert BUILD_ID in collect(tmp_path, "-m", "local_stack")
