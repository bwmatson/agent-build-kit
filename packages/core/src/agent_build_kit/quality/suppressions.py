"""Suppression markers a unit adds, each needing a reason on its line."""

import io
import re
import tokenize
from collections import Counter
from collections.abc import Mapping
from pathlib import Path

from agent_build_kit.model import Frozen
from agent_build_kit.quality.added_lines import AddedFile, git_lines

OPENERS = ("#", "//", "/*")
WORD = re.compile(r"[A-Za-z]{3,}")
CODES = r"(?::\s*[A-Z][A-Z0-9]*(?:\s*,\s*[A-Z][A-Z0-9]*)*)?"
BRACKETED = r"(?:\[[^\]]*\])?"
JS_KEYWORD = r"(?:\s+(?:next|file|if|else|start|stop))?"

# Each marker's pattern, and where its reason sits: after its rule list ("rest"), after ` -- `
# ("dashes") or after the first `: ` ("colon").
MARKERS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern), style)
    for pattern, style in (
        (rf"(?:(?:ruff|flake8):\s*)?noqa\b{CODES}", "rest"),
        (rf"type:\s*ignore{BRACKETED}", "rest"),
        (rf"pyrefly:\s*ignore{BRACKETED}", "rest"),
        (rf"pyright:\s*ignore{BRACKETED}", "rest"),
        (r"mypy:\s*ignore-errors", "rest"),
        (r"pylint:\s*disable(?:-next|-line)?\s*=\s*[\w-]+(?:\s*,\s*[\w-]+)*", "rest"),
        (r"nosec\b", "rest"),
        (r"pragma:\s*no\s*cover", "rest"),
        (r"(?:eslint|oxlint)-disable(?:-next-line|-line)?", "dashes"),
        (r"biome-ignore", "colon"),
        (r"@ts-(?:ignore|expect-error|nocheck)", "rest"),
        (rf"(?:istanbul|c8|v8)\s+ignore\b{JS_KEYWORD}", "rest"),
    )
)


class Suppression(Frozen):
    """An added suppression marker that carries no reason."""

    path: str
    line: int
    marker: str


def has_reason(style: str, rest: str) -> bool:
    """Whether the text after a marker holds a word of at least three letters as its reason."""
    if style == "dashes":
        rest = rest.partition(" -- ")[2]
    elif style == "colon":
        rest = rest.partition(": ")[2]
    return WORD.search(rest) is not None


def bare_markers(comment: str) -> list[str]:
    """The markers of a comment that carry no reason."""
    bare = []
    for pattern, style in MARKERS:
        found = pattern.search(comment)
        if found and not has_reason(style, comment[found.end() :]):
            bare.append(found.group(0))
    return bare


def comment_of_line(line: str) -> str | None:
    """The part of a line from its first comment opener, None when it has none."""
    starts = [at for opener in OPENERS if (at := line.find(opener)) >= 0]
    return line[min(starts) :] if starts else None


def python_comments(text: str) -> dict[int, str]:
    """Each line's comment, from the tokenizer, or line by line when the text does not tokenize."""
    comments: dict[int, str] = {}
    try:
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.type == tokenize.COMMENT:
                comments[token.start[0]] = token.string
    except (tokenize.TokenError, SyntaxError):
        comments = {}
        for number, line in enumerate(git_lines(text), 1):
            at = line.find("#")
            if at >= 0:
                comments[number] = line[at:]
    return comments


def scan_file(root: Path, file: AddedFile, moved: Counter[str]) -> list[Suppression]:
    """The bare suppressions on the added lines of one file that are not a moved line."""
    try:
        text = (root / file.path).read_bytes().decode("utf-8", errors="replace")
    except FileNotFoundError:
        return []
    lines = git_lines(text)
    comments = python_comments(text) if file.path.endswith(".py") else None
    found = []
    for number in sorted(file.added):
        if number > len(lines):
            continue
        stripped = lines[number - 1].strip()
        if moved[stripped] > 0:
            moved[stripped] -= 1
            continue
        comment = (
            comments.get(number) if comments is not None else comment_of_line(lines[number - 1])
        )
        for marker in bare_markers(comment or ""):
            found.append(Suppression(path=file.path, line=number, marker=marker))
    return found


def find_suppressions(
    root: Path, files: Mapping[str, AddedFile], *, require_reason: bool = True
) -> list[Suppression]:
    """The added suppressions without a reason, read from the files under `root`."""
    if not require_reason:
        return []
    moved = Counter(line.strip() for file in files.values() for line in file.removed)
    found: list[Suppression] = []
    for path in sorted(files):
        found.extend(scan_file(root, files[path], moved))
    return found
