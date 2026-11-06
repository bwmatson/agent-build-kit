"""Test support for reading prompt text: squeezed, and filled in as the nodes fill it."""

import string


def flat(text: str) -> str:
    """The text with every run of whitespace squeezed to one space."""
    return " ".join(text.split())


def placeholders(template: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


def filled(template: str, **fields: str) -> str:
    """The template with every placeholder filled in, as the nodes fill them; `fields` take the
    place of the stand-in text for the placeholders they name."""
    return template.format(**{**dict.fromkeys(placeholders(template), "x"), **fields})
