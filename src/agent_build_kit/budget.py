"""Cuts text to a size and shares a budget between the sections of a text.

The cuts (`cut_head`, `cut_tail`, `cut_middle`) return a text unchanged when it
fits, never return more than the size asked, and close any code fence or
collapsible block they leave open. `fit` renders the sections of a text within a
budget: everything in full when it fits, otherwise each section's smallest form
first, then the rest shared by weight, a section that needs less than its share
passing the remainder on.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Literal

from pydantic import Field

from agent_build_kit.model import Frozen

Boundary = Literal["char", "line", "paragraph"]

_JOINERS: dict[str, str] = {"char": "", "line": "\n", "paragraph": "\n\n"}
_RETRIES = 3


def _pieces(text: str, boundary: Boundary) -> list[str]:
    return list(text) if boundary == "char" else text.split(_JOINERS[boundary])


def _open_state(text: str) -> tuple[bool, int]:
    """Whether `text` leaves a code fence open, and how many details blocks."""
    lines = text.split("\n")
    fenced = sum(line.lstrip().startswith("```") for line in lines) % 2 == 1
    depth = sum(line.strip().startswith("<details") for line in lines) - sum(
        "</details>" in line for line in lines
    )
    return fenced, max(depth, 0)


def _closers(kept: str) -> list[str]:
    """What closes the code fence and details block `kept` leaves open."""
    fenced, depth = _open_state(kept)
    return (["```"] if fenced else []) + ["</details>"] * depth


def _openers(dropped: str) -> list[str]:
    """What reopens the fence and details blocks the dropped head left open."""
    fenced, depth = _open_state(dropped)
    return ["<details>"] * depth + (["```"] if fenced else [])


def _cut_side(text: str, size: int, boundary: Boundary, marker: str, head: bool) -> str:
    if len(text) <= size:
        return text
    pieces = _pieces(text, boundary)
    joiner = _JOINERS[boundary]

    def build(count: int) -> str:
        if head:
            kept = joiner.join(pieces[:count])
            body = "\n".join([kept, *_closers(kept)])
            parts = [body if _closers(kept) else kept, marker]
        else:
            split = len(pieces) - count
            kept = joiner.join(pieces[split:])
            openers = _openers(joiner.join(pieces[:split])) if kept else []
            parts = [marker, "\n".join([*openers, kept]) if openers else kept]
        return "\n\n".join(part for part in parts if part)

    if len(build(0)) > size:
        return marker[:size]
    low, high = 0, len(pieces)
    while low < high:
        middle = (low + high + 1) // 2
        if len(build(middle)) <= size:
            low = middle
        else:
            high = middle - 1
    return build(low)


def cut_head(text: str, size: int, boundary: Boundary = "line", marker: str = "") -> str:
    """The head of `text`, at most `size` characters, open fence and block closed.

    On the `char` boundary the cut is not guaranteed to be the longest that fits,
    because completing a closing fence can shorten what must be appended."""
    return _cut_side(text, size, boundary, marker, head=True)


def cut_tail(text: str, size: int, boundary: Boundary = "line", marker: str = "") -> str:
    """The tail of `text`, at most `size` characters.

    A fence or details block the dropped head left open is opened again before the
    tail, so the tail's own closing lines close it. On the `char` boundary the cut is
    not guaranteed to be the longest that fits."""
    return _cut_side(text, size, boundary, marker, head=False)


def cut_middle(text: str, size: int, boundary: Boundary = "line", marker: str = "") -> str:
    """The head and the tail of `text`, at most `size` characters in all."""
    if len(text) <= size:
        return text
    separator = "\n\n" if marker else "\n"
    overhead = len(marker) + 2 * len(separator) if marker else len(separator)
    if overhead >= size:
        return cut_head(text, size, boundary)
    head_size = (size - overhead) // 2
    tail_size = size - overhead - head_size
    parts = [cut_head(text, head_size, boundary), marker, cut_tail(text, tail_size, boundary)]
    return separator.join(part for part in parts if part)


class Section(Frozen):
    """One part of a text: how it renders at a size, and how it is weighed."""

    key: str
    render: Callable[[int], str]
    natural: int
    smallest: int
    weight: int = Field(default=1, ge=1)
    ceiling: int | None = None
    required: bool = False


def _allocate(sections: Sequence[Section], budget: int, separator: str) -> dict[int, int]:
    """Size per kept section (by index): smallest forms, then weighted shares."""
    natural = [s.natural if s.ceiling is None else min(s.natural, s.ceiling) for s in sections]
    smallest = [min(s.smallest, n) for s, n in zip(sections, natural, strict=True)]
    kept = list(range(len(sections)))

    def gaps() -> int:
        return max(len(kept) - 1, 0) * len(separator)

    while kept and sum(smallest[i] for i in kept) + gaps() > budget:
        droppable = [i for i in kept if not sections[i].required]
        if not droppable:
            break
        kept.remove(min(droppable, key=lambda i: (sections[i].weight, -i)))

    if sum(natural[i] for i in kept) + gaps() <= budget:
        return {i: natural[i] for i in kept}
    if sum(smallest[i] for i in kept) + gaps() > budget:
        return {i: smallest[i] for i in kept}

    allocation = {i: smallest[i] for i in kept}
    open_ = list(kept)
    saturated: list[int] = []
    while True:
        weight = sum(sections[i].weight for i in open_)
        pool = budget - gaps() - sum(natural[i] for i in saturated)
        pool -= sum(smallest[i] for i in open_)
        newly = [
            i for i in open_ if (natural[i] - smallest[i]) * weight <= pool * sections[i].weight
        ]
        if not newly or not open_:
            break
        saturated.extend(newly)
        open_ = [i for i in open_ if i not in newly]
    for i in saturated:
        allocation[i] = natural[i]
    if open_:
        shares = {i: pool * sections[i].weight // weight for i in open_}
        leftover = pool - sum(shares.values())
        for i in open_:
            extra = 1 if leftover > 0 else 0
            leftover -= extra
            allocation[i] = min(natural[i], smallest[i] + shares[i] + extra)
    return allocation


def fit(sections: Sequence[Section], budget: int, separator: str = "\n\n") -> str:
    """The sections rendered and joined, never more than `budget` characters."""
    allocation = _allocate(sections, budget, separator)
    floors = {i: min(sections[i].smallest, allocation[i]) for i in allocation}
    text = ""
    for attempt in range(_RETRIES + 1):
        rendered = [sections[i].render(allocation[i]) for i in sorted(allocation)]
        text = separator.join(part for part in rendered if part)
        if len(text) <= budget or attempt == _RETRIES:
            break
        room = {i: allocation[i] - floors[i] for i in allocation}
        roomiest = max(sorted(room), key=lambda i: room[i])
        if room[roomiest] <= 0:
            break
        allocation[roomiest] -= min(room[roomiest], len(text) - budget)
    if len(text) <= budget:
        return text
    return cut_head(text, budget, "line") or cut_head(text, budget, "char")
