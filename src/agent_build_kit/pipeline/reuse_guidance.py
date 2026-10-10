"""The packaged prompt part that tells a builder how to find and reuse existing code."""

from __future__ import annotations


def reuse_guidance() -> str:
    """The packaged text appended to the full form of each builder prompt."""
    raise NotImplementedError
