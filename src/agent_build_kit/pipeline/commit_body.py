"""The body of a build commit: why the change exists, composed without a model call."""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

from agent_build_kit.pipeline.pr_body import why_text
from agent_build_kit.pipeline.stack_runner import GroupStep

SENTENCE_LIMIT = 200
TESTS_SENTENCE = "The tests come first and fail until the implementation."
CODE_SENTENCE = "With this in, the tests of the previous commit pass."

_FIRST_SENTENCE = re.compile(r"(.+?[.!?])(?:\s|$)", re.S)
_TRAILER_LIKE = re.compile(r"^([\w-]+):(?=\s|$)")


def _bounded(text: str) -> str:
    """One line of text, cut at a word boundary with an ellipsis when over the limit."""
    text = " ".join(text.split())
    if len(text) <= SENTENCE_LIMIT:
        return text
    return text[:SENTENCE_LIMIT].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def _plain(text: str) -> str:
    """The text with each line reworded so git reads none as a comment or a trailer."""
    lines = []
    for raw in text.splitlines():
        line = raw.strip().lstrip("#").strip()
        lines.append(_TRAILER_LIKE.sub(r"\1 —", line))
    return "\n".join(line for line in lines if line)


def _first_sentence(why: str) -> str:
    paragraph = why.strip().split("\n\n")[0]
    found = _FIRST_SENTENCE.match(" ".join(paragraph.split()))
    return found[1] if found else paragraph


def commit_body(steps: Sequence[GroupStep], *, tests: bool) -> str:
    """The body of the tests commit (`tests`) or the implementation commit for these groups:
    the first sentence of each change's proposal Why, once, then the groups' goals. Empty when
    there is neither."""
    sentences: list[str] = []
    seen: set[str] = set()
    for step in steps:
        directory = Path(step.change_dir)
        if step.change_dir in seen:
            continue
        seen.add(step.change_dir)
        why = _first_sentence(why_text(directory.parent, directory.name))
        if why:
            sentences.append(why)
    sentences.extend(step.goal for step in steps if step.goal)
    parts = [_bounded(_plain(sentence)) for sentence in sentences]
    parts = [part for part in parts if part]
    if not parts:
        return ""
    return "\n\n".join([TESTS_SENTENCE if tests else CODE_SENTENCE, *parts])
