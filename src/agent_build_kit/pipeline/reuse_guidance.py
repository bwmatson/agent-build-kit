"""The packaged prompt part that tells a builder how to find and reuse existing code."""

from __future__ import annotations

from importlib import resources
from typing import Literal

Kind = Literal["source", "tests"]

_FILES = {"source": "reuse-guidance.md", "tests": "reuse-guidance-tests.md"}


def reuse_guidance(kind: Kind = "source") -> str:
    """The packaged text appended to the full form of each builder prompt: the `"source"`
    version for the prompts that change source, the `"tests"` version for those that write tests."""
    if kind not in _FILES:
        raise ValueError(f"no {kind!r} reuse guidance; one of {', '.join(_FILES)}")
    return (
        resources.files("agent_build_kit").joinpath("templates", _FILES[kind]).read_text().strip()
    )
