"""The packaged table of the test standards the builders are told once per session."""

from __future__ import annotations

from importlib import resources


def standards_guidance() -> str:
    """The packaged table: a heading line, then one line per standard, each opening with its ID."""
    return (
        resources.files("agent_build_kit")
        .joinpath("templates", "test-standards.md")
        .read_text()
        .strip()
    )
