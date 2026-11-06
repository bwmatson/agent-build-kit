"""The packaged prompt part that tells a builder how to find and reuse existing code."""

from __future__ import annotations

from importlib import resources


def reuse_guidance(kind: str = "source") -> str:
    """The packaged text appended to the full form of each builder prompt: the `"source"`
    version for the prompts that change source, the `"tests"` version for those that write tests."""
    return (
        resources.files("agent_build_kit")
        .joinpath("templates", "reuse-guidance.md")
        .read_text()
        .strip()
    )
