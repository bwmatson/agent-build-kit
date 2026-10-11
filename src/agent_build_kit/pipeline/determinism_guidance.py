"""The packaged rules that keep a test from passing alone and failing under load."""

from __future__ import annotations

from importlib import resources


def determinism_guidance() -> str:
    """The packaged text, shared by the test-writing prompt and the reviewer's checklist."""
    return (
        resources.files("agent_build_kit")
        .joinpath("templates", "determinism-guidance.md")
        .read_text()
        .strip()
    )
