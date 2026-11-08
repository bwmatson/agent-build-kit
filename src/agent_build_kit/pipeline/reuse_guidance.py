"""The packaged prompt part that tells a builder how to find and reuse existing code."""

from __future__ import annotations

from typing import Literal

from agent_build_kit.pipeline.packaged_template import packaged_template

Kind = Literal["source", "tests"]

_FILES = {"source": "reuse-guidance.md", "tests": "reuse-guidance-tests.md"}


def reuse_guidance(kind: Kind = "source") -> str:
    """The packaged text appended to the full form of each builder prompt: the `"source"`
    version for the prompts that change source, the `"tests"` version for those that write tests."""
    if kind not in _FILES:
        raise ValueError(f"no {kind!r} reuse guidance; one of {', '.join(_FILES)}")
    return packaged_template(_FILES[kind])
