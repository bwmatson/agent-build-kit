"""The packaged rules that keep a test from passing alone and failing under load."""

from __future__ import annotations

from agent_build_kit.pipeline.packaged_template import packaged_template


def determinism_guidance() -> str:
    """The packaged text, shared by the test-writing prompt and the reviewer's checklist."""
    return packaged_template("determinism-guidance.md")
