"""The node-npm red command takes ids and keeps whole files (spec: red-check-by-id)."""

from __future__ import annotations

from typing import Any

from agent_build_kit import profiles


def test_ids_are_ignored_and_the_files_are_run_whole() -> None:
    profile: Any = profiles.get("node-npm")
    files = ["src/a.test.ts"]

    command = profile.red_command(files, ["src/a.test.ts::adds"])

    assert command == profile.red_command(files)
    assert "adds" not in command
