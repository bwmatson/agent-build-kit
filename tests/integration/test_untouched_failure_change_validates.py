"""The change written for a pre-existing failing test, and its successor, pass
`openspec validate --strict` (spec: tier2-failures). Needs node (npx) and, on the first
run, the network."""

from __future__ import annotations

import shutil

import pytest

from agent_build_kit import openspec
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.untouched_failures import ensure_fix
from tests.openspec_cli import require
from tests.pipeline.test_flake_fix_change import change_with_unit, code_repo
from tests.untouched_failure_fakes import failing

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("npx") is None, reason="npx is not on PATH"),
    pytest.mark.usefixtures("openspec_cli"),
]


def validated(inst: Installation, name: str) -> None:
    result = require(openspec.run(["validate", name, "--strict", "--json"], cwd=inst.root))

    assert result.returncode == 0, result.stdout + result.stderr
    assert '"failed": 0' in result.stdout


def test_the_written_change_and_its_successor_pass_openspec_validate(
    installation: Installation,
) -> None:
    code_repo(installation)
    (installation.specs_dir / "specs").mkdir(parents=True, exist_ok=True)
    unit = change_with_unit(installation, "feature", "feature/1")
    first = ensure_fix(installation, failing(unit=unit.id), unit, say=lambda line: None)
    validated(installation, first)

    archive = installation.changes_dir / "archive"
    archive.mkdir()
    (installation.changes_dir / first).rename(archive / f"2026-03-02-{first}")
    successor = ensure_fix(installation, failing(unit=unit.id), unit, say=lambda line: None)

    assert successor != first
    validated(installation, successor)
