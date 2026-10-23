"""The interface every notification provider implements."""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol


class CardKind(StrEnum):
    REVIEW = "review"
    FAILED = "failed"
    HELD = "held"
    DIGEST = "digest"


class ProviderError(Exception):
    """A provider could not show or clear a card: it exited non-zero or timed out."""


class Notifier(Protocol):
    def show(self, id: str, title: str, body: str, link: str) -> None: ...

    def clear(self, id: str) -> None: ...
