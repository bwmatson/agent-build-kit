"""The paths a task group names: one reader for project resolution and the e2e product-path
warning (spec: project-resolution)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import TYPE_CHECKING

from agent_build_kit.pipeline.commit_order import CONFIG_SUFFIXES, classify_paths

if TYPE_CHECKING:
    from agent_build_kit.pipeline.work_graph import TaskGroup

_TICKED = re.compile(r"`([^`]+)`")
_LINE_SUFFIX = re.compile(r":\d+$")
_EXTENSION = re.compile(r"\.[A-Za-z0-9]+$")
_NOT_A_PATH = re.compile(r"[\s=(<]")
# Lines of a group that say something other than which paths it changes.
_NOT_CHANGES = re.compile(
    r"^\s*(?:Not changed|Planning note|Reads|Paths|Needs|Support|Check|Manual|Separate|"
    r"Independent|Split|Priority|Acceptance):",
    re.I,
)
_VERIFY = re.compile(r"\bVerify:.*", re.I)
_SENTENCE_END = re.compile(r"(?<=\.)\s+")
_NOT_A_CHANGE = re.compile(r"\b(?:unchanged|must not|do not)\b.*", re.I)


def _is_path_token(token: str) -> bool:
    """Whether a backticked token can be a path: not a flag, URL or variable, and no spaces,
    assignments, calls or placeholders."""
    return not (token.startswith(("-", "http", "$")) or _NOT_A_PATH.search(token))


def line_paths(line: str) -> list[str]:
    """The repo paths a task line names in backticks: tokens with a `/` or a file extension,
    without a trailing `:<line>`, `::<test id>` or `/`; URLs, flags, assignments, globs and
    symbols are skipped."""
    found: list[str] = []
    for token in _TICKED.findall(line):
        if not _is_path_token(token) or "*" in token:
            continue
        cleaned = _LINE_SUFFIX.sub("", token.split("::", 1)[0]).rstrip("/")
        if cleaned and ("/" in cleaned or _EXTENSION.search(cleaned)):
            found.append(cleaned)
    return found


def _glob_prefix(token: str) -> str | None:
    """The literal directory prefix of a glob token (`web/src/**` is `web/src/`), None when the
    token is not a glob or has no directory before it."""
    if not _is_path_token(token):
        return None
    at = [i for char in "*?[" if (i := token.find(char)) >= 0]
    if not at:
        return None
    prefix = token[: min(at)]
    prefix = prefix[: prefix.rfind("/") + 1]
    return prefix or None


def changed_paths(line: str, projects: Sequence[str]) -> list[str]:
    """The paths one line of a group names as changes: backticked paths, globs by their literal
    prefix and unticked words anchored on a declared project (`projects`), in the order they
    appear, leaving out a `Verify:` segment and a sentence from "unchanged", "must not" or
    "do not" on. A line that says what is not changed names none."""
    if _NOT_CHANGES.match(line):
        return []
    text = _VERIFY.sub("", line)
    anchored = (
        re.compile(rf"(?<![\w`/.-])(?:{'|'.join(re.escape(p) for p in projects)})/[^\s`,;)]*")
        if projects
        else None
    )
    found: list[str] = []
    for sentence in _SENTENCE_END.split(text):
        sentence = _NOT_A_CHANGE.sub("", sentence)
        found += line_paths(sentence)
        found += [prefix for t in _TICKED.findall(sentence) if (prefix := _glob_prefix(t))]
        if anchored:
            found += [w.rstrip(".:") for w in anchored.findall(_TICKED.sub(" ", sentence))]
    return list(dict.fromkeys(found))


def named_paths(group: TaskGroup, projects: Sequence[str]) -> list[str]:
    """The paths `group` names as changes: its `Paths:` line when it has one, else the paths of
    its lines that are changes, with globs by their literal prefix and unticked words anchored
    on a declared project's path (`projects`, as a heading writes them)."""
    if group.paths:
        return [_glob_prefix(entry) or entry.rstrip("/") for entry in group.paths]
    found = [path for line in group.body for path in changed_paths(line, projects)]
    return list(dict.fromkeys(found))


def allows_no_code(paths: Sequence[str]) -> bool:
    """Whether the paths a group names are all documents or configuration, so the group may be
    built without code. No path at all cannot be classified and allows nothing."""
    labels = classify_paths(list(paths))
    return bool(paths) and all(
        label == "docs" or (label == "code" and path.endswith(CONFIG_SUFFIXES))
        for path, label in labels.items()
    )
