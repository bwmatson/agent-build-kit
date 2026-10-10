"""The change written for a flaky test passes `openspec validate --strict`
(spec: flaky-tests). Needs node (npx) and, on the first run, the network."""

from __future__ import annotations

import shutil

import pytest

from agent_build_kit import openspec
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.flakes import wait_on_fix
from tests.pipeline.test_flake_fix_change import change_with_unit, code_repo, flaked

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("npx") is None, reason="npx is not on PATH"),
]


def test_the_written_change_passes_openspec_validate(installation: Installation) -> None:
    code_repo(installation)
    (installation.specs_dir / "specs").mkdir(parents=True, exist_ok=True)
    unit = change_with_unit(installation, "feature", "feature/1")
    name = wait_on_fix(installation, flaked(), unit)
    assert name

    result = openspec.run(["validate", name, "--strict", "--json"], cwd=installation.root)

    assert result.returncode == 0, result.stdout + result.stderr
    assert '"failed": 0' in result.stdout
