"""Cuts text to a size and shares a budget between the sections of a text."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Literal

from agent_build_kit.model import Frozen

Boundary = Literal["char", "line", "paragraph"]


def cut_head(text: str, size: int, boundary: Boundary = "line", marker: str = "") -> str:
    """The head of `text`, at most `size` characters, open fence and block closed."""
    raise NotImplementedError


def cut_tail(text: str, size: int, boundary: Boundary = "line", marker: str = "") -> str:
    """The tail of `text`, at most `size` characters, open fence and block closed."""
    raise NotImplementedError


def cut_middle(text: str, size: int, boundary: Boundary = "line", marker: str = "") -> str:
    """The head and the tail of `text`, at most `size` characters in all."""
    raise NotImplementedError


class Section(Frozen):
    """One part of a text: how it renders at a size, and how it is weighed."""

    key: str
    render: Callable[[int], str]
    natural: int
    smallest: int
    weight: int = 1
    ceiling: int | None = None
    required: bool = False


def fit(sections: Sequence[Section], budget: int, separator: str = "\n\n") -> str:
    """The sections rendered and joined, never more than `budget` characters."""
    raise NotImplementedError
