"""node-npm's clean command adds `tsc --noEmit` when types are asked for (spec: test-stubs)."""

from __future__ import annotations

from agent_build_kit.profiles.node_npm import PROFILE


def test_the_clean_command_is_lint_and_the_format_check_unless_types_are_asked_for() -> None:
    plain = PROFILE.clean_command()
    with_types = PROFILE.clean_command(types=True)

    assert "tsc" not in plain
    assert "oxlint" in plain
    assert "oxfmt --check" in plain
    assert with_types != plain


def test_the_clean_command_with_types_runs_tsc_in_the_same_shell_string() -> None:
    plain = PROFILE.clean_command()
    with_types = PROFILE.clean_command(types=True)

    assert with_types.startswith(plain)
    assert with_types.count("tsc --noEmit") == 1
    assert "&&" in with_types.removeprefix(plain)
