"""The lines of a YAML text with their endings, and the line edits that keep every other byte.

Shared by the edits that change a configuration file as text (`abk policy apply`, the limits
migration): the parse finds where, and these helpers find the end of a node and insert lines."""

from __future__ import annotations

import re

__all__ = [
    "leading_spaces",
    "insert_lines",
    "is_content",
    "is_marker",
    "node_end",
    "split_lines",
    "strip_comment",
]


def split_lines(text: str) -> list[str]:
    """The lines of `text` with their endings, split at newlines only, so the join is the text."""
    parts = text.split("\n")
    lines = [part + "\n" for part in parts[:-1]]
    if parts[-1]:
        lines.append(parts[-1])
    return lines


def leading_spaces(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def is_content(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and not stripped.startswith("#")


def is_marker(line: str) -> bool:
    return line.startswith(("---", "...")) and line[3:4] in ("", " ", "\t", "\r", "\n")


def node_end(lines: list[str], start: int, col: int, *, beside_dash: bool = False) -> int:
    """The last content line of the node that starts on line `start` at column `col`: the last
    non-blank, non-comment line before the first content line indented at or under `col` (a dash
    at `col` still belongs to a mapping key's list when `beside_dash`), or a document marker, or
    the end of the file. Comments and blank lines after it are not part of the node."""
    last = start
    for number in range(start + 1, len(lines)):
        line = lines[number]
        if not is_content(line):
            continue
        if is_marker(line):
            break
        if leading_spaces(line) <= col and not (
            beside_dash and leading_spaces(line) == col and line.lstrip().startswith("- ")
        ):
            break
        last = number
    return last


def strip_comment(line: str) -> str:
    return re.sub(r"(^|\s)#.*$", "", line.rstrip("\r\n")).rstrip()


def insert_lines(lines: list[str], at: int, new: list[str], eol: str) -> None:
    if at > 0 and not lines[at - 1].endswith("\n"):
        lines[at - 1] += eol
    lines[at:at] = [line + eol for line in new]
