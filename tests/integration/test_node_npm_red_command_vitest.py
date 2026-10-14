"""The node-npm `red_command` against the real Vitest (spec: node-npm-red-and-stubs).

Vitest takes the files it is given as filters, and a filter is a substring match on a test
file's path relative to the project: `src/a.test.ts` also selects `other/src/a.test.ts`, and
an absolute path is turned back into that same relative substring. No Vitest argument selects
one file exactly, so the report is what tells the files apart: each test suite in it is named
by its file's path, which is what lets a red judge keep only the files it was given.
"""

import os
import subprocess
from pathlib import Path

import pytest

from agent_build_kit.pipeline.red_check import parse_report, split_report
from agent_build_kit.profiles.node_npm import PROFILE

pytestmark = pytest.mark.integration

TEST = "import {{ expect, test }} from 'vitest';\ntest('t', () => {{ expect(1).toBe({n}); }});\n"


def test_the_report_names_each_test_file_so_files_outside_the_given_ones_can_be_told_apart(
    tmp_path: Path,
) -> None:
    (tmp_path / "package.json").write_text('{"name": "case", "type": "module"}\n')
    for directory, expected in (("src", 2), ("other/src", 1)):
        (tmp_path / directory).mkdir(parents=True)
        (tmp_path / directory / "a.test.ts").write_text(TEST.format(n=expected))

    done = subprocess.run(
        PROFILE.red_command(["src/a.test.ts"]),
        shell=True,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "npm_config_yes": "true"},
    )

    assert done.returncode != 0
    report, _ = split_report(done.stdout + done.stderr)
    assert report is not None
    suites = {suite.get("name"): suite for suite in parse_report(report).iter("testsuite")}
    assert "src/a.test.ts" in suites
    assert list(suites["src/a.test.ts"].iter("failure")), "the given file is the failing one"
    assert set(suites) <= {"src/a.test.ts", "other/src/a.test.ts"}, "every suite is named by path"
