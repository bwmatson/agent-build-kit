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


def test_a_file_named_by_the_convention_is_run_by_the_test_name_of_its_id() -> None:
    profile: Any = profiles.get("node-npm")

    command = profile.red_command(["src/a.e2e.test.ts"], ["src/a.e2e.test.ts::adds two numbers"])

    assert "src/a.e2e.test.ts" in command
    assert "-t" in command
    assert "adds two numbers" in command
