"""The shell wrapper `red_command` builds, run the way the gate runs it.

The wrapper writes pytest's report to a temp file, prints it after the console
behind a marker and keeps pytest's exit status. If any of that broke, every run
would quietly fall back to the console, or a failing run would look passing.
"""

import subprocess
import sys
from pathlib import Path

import pytest

from agent_build_kit.pipeline.red_check import red_check, split_report
from agent_build_kit.profiles.python_uv import PROFILE

pytestmark = pytest.mark.integration


def test_the_red_command_exits_non_zero_and_prints_a_report_the_red_check_accepts(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    bin_dir = tmp_path / "bin"
    project.mkdir()
    bin_dir.mkdir()
    (project / "test_thing.py").write_text("def test_new():\n    assert 1 == 2\n")
    # `uv run pytest ...` resolves a project environment; this runs the same pytest here.
    shim = bin_dir / "uv"
    shim.write_text(f'#!/bin/sh\nshift\nexec "{sys.executable}" -m "$@"\n')
    shim.chmod(0o755)

    done = subprocess.run(
        PROFILE.red_command(["test_thing.py"]),
        shell=True,
        cwd=project,
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path)},
    )

    assert done.returncode != 0
    report, console = split_report(done.stdout + done.stderr)
    assert report is not None
    assert "1 failed" in console
    result = red_check(report)
    assert result.verdict == "accepted"
    assert result.tests == ("test_thing::test_new",)
