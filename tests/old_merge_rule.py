"""Test support: the statements of the old rule about who merges, found in a text."""

import re

OLD_RULE = re.compile(
    r"\b(?:(?:human|person)\s+merges\s+(?:every\w*|each|all|it|them)|pipeline\s+never\s+merges)\b",
    re.I,
)


def statements(text: str) -> list[int]:
    """The 1-based line each statement of the old rule starts on, across wrapped lines."""
    return [text.count("\n", 0, hit.start()) + 1 for hit in OLD_RULE.finditer(text)]
