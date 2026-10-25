"""Test support: the statements of the old rule about who merges, found in a text."""

import re

OLD_RULE = re.compile(
    r"\b(?:(?:humans?|persons?|people)\s+(?:reviews?\s+and\s+)?merges?\b"
    r"(?!\s+(?:what\s+was\s+not\s+auto-landed|any\s+other|each\s+pull\s+request\s+that))"
    r"|pipeline\s+never\s+merges)",
    re.I,
)


def statements(text: str) -> list[int]:
    """The 1-based line each statement of the old rule starts on, across wrapped lines."""
    return [text.count("\n", 0, hit.start()) + 1 for hit in OLD_RULE.finditer(text)]
