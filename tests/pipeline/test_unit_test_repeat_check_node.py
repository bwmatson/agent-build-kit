"""A unit that changes a node test file has that file run again under load after unit-test
passes (spec: node-npm-lint-and-test). The command runner is the faked boundary."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from agent_build_kit import profiles
from agent_build_kit.pipeline.wiring import build_unit_test
from agent_build_kit.profiles.base import ToolchainProfile
from tests.conftest import make_installation
from tests.e2e_scope_fakes import Ran, branch
from tests.node_workspace import manifest

TEST = "src/a.test.ts"


def test_a_changed_node_test_file_is_run_again_by_its_path(tmp_path: Path) -> None:
    repo, base = branch(tmp_path, {TEST: "// changed\n"}, base_files={TEST: ""})
    manifest(repo, "solo")
    make_installation(tmp_path / "planning", limits={"unit_test_repeat_runs": 2})
    ran = Ran("", 0)

    passed, _ = build_unit_test(
        profile=cast(ToolchainProfile, profiles.get("node-npm")),
        run=ran,
        changed=lambda *a: [TEST],
    )(cwd=repo, base=base)

    assert passed
    assert len([c for c in ran.commands if c[5:] == [TEST]]) == 2
