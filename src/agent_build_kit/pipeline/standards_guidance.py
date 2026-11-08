"""The packaged table of the test standards the builders are told once per session."""

from __future__ import annotations

from agent_build_kit.pipeline.packaged_template import packaged_template


def standards_guidance() -> str:
    """The packaged table: a heading line, then one line per standard, each opening with its ID."""
    return packaged_template("test-standards.md")
