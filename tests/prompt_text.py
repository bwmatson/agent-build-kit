"""Test support for reading prompt text: squeezed, and filled in as the nodes fill it."""

import re
import string
from pathlib import Path


def flat(text: str) -> str:
    """The text with every run of whitespace squeezed to one space."""
    return " ".join(text.split())


def section(path: Path, heading: str) -> str:
    """The squeezed text under the heading naming `heading`, to the next heading of its level or
    above."""
    text = path.read_text()
    match = re.search(rf"^(#+) .*{re.escape(heading)}.*$", text, re.M)
    assert match, f"{path.name} has no heading naming {heading}"
    rest = text[match.end() :]
    following = re.search(rf"^#{{1,{len(match[1])}}} ", rest, re.M)
    return flat(rest[: following.start()] if following else rest)


def placeholders(template: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


def filled(template: str, **fields: str) -> str:
    """The template with every placeholder filled in, as the nodes fill them; `fields` take the
    place of the stand-in text for the placeholders they name."""
    return template.format(**{**dict.fromkeys(placeholders(template), "x"), **fields})
