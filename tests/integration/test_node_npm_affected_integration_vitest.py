"""The node-npm affected run against the real Vitest (spec: integration-tests-run-in-the-unit-gate).

A config that excludes the integration files keeps them out of an affected run too, since the
runner adds a command-line exclude to the config's list and never removes one from it. The
profile's affected command therefore runs through a config that drops those patterns; this
proves it against the real runner.
"""

import os
import subprocess
from pathlib import Path

import pytest

from agent_build_kit.pipeline.red_check import parse_report, split_report
from agent_build_kit.profiles.node_npm import PROFILE

pytestmark = pytest.mark.integration

CONFIG = (
    'export default { test: { exclude: ["**/*.integration.test.ts", "**/node_modules/**"] } };\n'
)
SOURCE = "export const value = 1;\n"
TEST = (
    "import { expect, test } from 'vitest';\n"
    "import { value } from './x';\n"
    "test('t', () => { expect(value).toBe(1); });\n"
)


# npx downloads vitest at test time, which a slow registry can stretch past the default limit.
@pytest.mark.time_limit(180)
def test_an_affected_run_runs_the_integration_test_the_config_excludes(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name": "case", "type": "module"}\n')
    (tmp_path / "vitest.config.ts").write_text(CONFIG)
    (tmp_path / "src").mkdir()
    (tmp_path / "src/x.ts").write_text(SOURCE)
    (tmp_path / "src/x.test.ts").write_text(TEST)
    (tmp_path / "src/x.integration.test.ts").write_text(TEST)

    commands = PROFILE.affected_test_commands(
        tmp_path, ["src/x.ts"], [], seed=tmp_path / "seed", root_extras=[]
    )
    assert commands is not None
    (command,) = commands
    done = subprocess.run(
        command,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "npm_config_yes": "true"},
    )

    report, _ = split_report(done.stdout + done.stderr)
    assert report is not None, done.stdout + done.stderr
    suites = {suite.get("name") for suite in parse_report(report).iter("testsuite")}
    assert "src/x.integration.test.ts" in suites, done.stdout + done.stderr
    assert "src/x.test.ts" in suites
