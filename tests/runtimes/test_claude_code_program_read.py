"""The runtime's read grant covers where the `claude` program is found and where a link to it
points (spec: product-defects, group 1)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit import config
from agent_build_kit.config import WorkspaceConfig
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime
from tests.runtimes.acp_sandbox_support import claude_stand_in


def test_the_read_grant_holds_the_link_s_folder_and_its_target_s_folder(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    program = claude_stand_in(real / "claude", "echo done\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    link = bin_dir / "claude-link"
    link.symlink_to(program)
    config.activate(
        WorkspaceConfig.model_validate({"runtimes": {"claude_code": {"command": [str(link)]}}})
    )

    read = ClaudeCodeRuntime().sandbox_paths()["read"]

    assert str(link.parent) in read
    assert str(program.resolve().parent) in read
