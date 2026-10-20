"""The build the acceptance test runs in its own session is an e2e test there, so it is held to
the e2e time limit and not the 60-second default, which a real build overruns.

Collected under the command the driver runs, so a change to that command that stops the build
being selected, or a marker the time-limit plugin does not see, fails here."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

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


ACCEPTANCE = build.REPO / "tests" / "integration" / "test_replay_unit.py"
ACCEPTANCE_TESTS = {
    "test_a_live_pass_in_record_mode_is_promoted_to_cassettes",
    "test_an_unchanged_rerun_replays_the_deterministic_calls_and_is_labelled",
    "test_an_edited_task_sends_exactly_the_changed_calls_live",
}


def collected_ids(selection: str) -> set[str]:
    done = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-o",
            "addopts=",
            "--collect-only",
            "-q",
            "-m",
            selection,
            str(ACCEPTANCE),
        ],
        cwd=build.REPO,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return {line.rpartition("::")[2] for line in done.stdout.splitlines() if "::" in line}


def test_the_build_session_declares_the_session_rule(pytester: pytest.Pytester) -> None:
    # The fixture the replay plugin reads the build's rules from, resolved as the plugin would.
    pytester.makepyfile(
        test_rules="""
        from tests.integration.replay_unit_build import SESSION_RULE, replay_rules  # noqa: F401

        def test_declared(replay_rules):
            assert replay_rules == [SESSION_RULE]
        """
    )

    pytester.runpytest_inprocess("-p", "no:cacheprovider").assert_outcomes(passed=1)


def test_the_acceptance_runs_on_claude_code_alone() -> None:
    assert collected_ids("local_stack and runtime_claude_code") == ACCEPTANCE_TESTS
    assert collected_ids("local_stack and runtime_acp") == set()


def test_the_build_without_the_drivers_environment_is_skipped_naming_what_is_missing(
    tmp_path: Path,
) -> None:
    env = {
        name: value
        for name, value in os.environ.items()
        if name not in build.DRIVER_ENVIRONMENT or name == build.ROOT
    }
    done = subprocess.run(
        [*build.session_argv(tmp_path), "-rs"],
        cwd=build.REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    output = done.stdout + done.stderr

    assert "1 skipped" in output, output
    assert build.CASSETTES in output and build.MARKER in output, output
    assert "error" not in output.lower(), output
