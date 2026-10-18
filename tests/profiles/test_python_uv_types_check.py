"""python-uv's clean command skips the type hook unless types are asked for (spec: test-stubs)."""

from __future__ import annotations

from agent_build_kit.profiles.python_uv import PROFILE

TYPE_HOOK = "pyrefly-check"


def test_the_clean_command_skips_the_type_hook_unless_types_are_asked_for() -> None:
    with_types = PROFILE.clean_command(types=True)

    assert TYPE_HOOK in PROFILE.clean_command()
    assert "SKIP" in PROFILE.clean_command()
    assert "pre-commit run --all-files" in with_types
    assert f"SKIP={TYPE_HOOK}" not in with_types


def test_the_clean_command_with_types_skips_no_hook() -> None:
    command = PROFILE.clean_command(types=True)

    assert "SKIP" not in command
    assert command != PROFILE.clean_command()
