"""Stand-ins for the active set of known secret values."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager

from agent_build_kit import redaction
from agent_build_kit.redaction import Redactor

NOTICE = "[redaction failed: text withheld]"
SECRET = "s3cret-value-0001"
NAME = "API_KEY"
FAILURE_MESSAGE = "boom quoting the text"


class BrokenRedactor(Redactor):
    """A set whose redaction raises, with a message that quotes the text."""

    def redact(self, text: str) -> str:
        raise RuntimeError(f"{FAILURE_MESSAGE}: {text}")


@contextmanager
def known(values: Mapping[str, str] | None = None, *, broken: bool = False) -> Iterator[None]:
    """Make `values` (default: `API_KEY`=`SECRET`) the active set for the block."""
    previous = redaction.active()
    held = {NAME: SECRET} if values is None else values
    redaction.activate(BrokenRedactor(held) if broken else Redactor(held))
    try:
        yield
    finally:
        redaction.activate(previous)
