"""Merge the recommended policy into a known agent's configuration, over its descriptor.

Add only, and by text: the parse finds the list and computes what is missing, and the missing
lines are inserted into the original text, so every other byte of the operator's file is as it
was. The document is never dumped. The original is copied once to `<file>.abk-backup`, the write
goes through a temporary file beside the target, and a file the engine cannot change by pure
insertion is refused with the reason. The engine takes the resolved home as an argument;
`resolve_home` is the one place a variable is looked at.
"""

from __future__ import annotations

import difflib
import os
import re
import shutil
import tempfile
from collections.abc import Callable, Iterable, Mapping
from enum import StrEnum
from pathlib import Path
from typing import Any, NamedTuple

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.error import YAMLError
from ruamel.yaml.nodes import ScalarNode

from agent_build_kit.model import Frozen
from agent_build_kit.runtimes.known_agents import ApplyFormat, ApplyPolicy, YamlVersion
from agent_build_kit.runtimes.recommended_policy import patterns
from agent_build_kit.settings import named_value
from agent_build_kit.yaml_lines import (
    insert_lines,
    is_content,
    is_marker,
    leading_spaces,
    node_end,
    split_lines,
    strip_comment,
)

BACKUP_SUFFIX = ".abk-backup"
STR_TAG = "tag:yaml.org,2002:str"
DEFAULT_STEP = 2


class ApplyRefused(Exception):
    """The configuration cannot be merged into; nothing was written."""


class Status(StrEnum):
    WRITTEN = "written"
    WOULD_WRITE = "would_write"  # a dry run that found something to add
    UNCHANGED = "unchanged"
    ABSENT = "absent"


class ApplyResult(Frozen):
    path: Path
    status: Status
    message: str = ""
    diff: str = ""
    added: tuple[str, ...] = ()
    backup: Path | None = None
    # The toolset's list before and after, when it was asked for and differs.
    toolset_change: tuple[tuple[str, ...], tuple[str, ...]] | None = None


class Merged(Frozen):
    text: str
    added: tuple[str, ...]
    toolset_change: tuple[tuple[str, ...], tuple[str, ...]] | None


# A writer reads a configuration's text, adds `wanted` to the list at the descriptor's deny path
# and, when `toolset` is given, sets the list at its path, by inserting into the text; it raises
# `ApplyRefused` naming `label`.
Writer = Callable[[str, ApplyPolicy, list[str], tuple[str, ...] | None, str], Merged]

# `key:` at the start of `text`, the key plain or quoted.
_KEY = re.compile(
    r"""(?:"(?:[^"\\]|\\.)*"|'(?:[^']|'')*'|[^\s:#'"\[{&*!|>%@`-][^:#]*?)\s*:(?=\s|$)"""
)
_DASH_PREFIX = re.compile(r"\s*-\s+")
_INDICATORS = "-?:,[]{}#&*!|>'\"%@`"


def _dotted(path: tuple[str, ...]) -> str:
    return ".".join(path)


# --- reading -----------------------------------------------------------------------------------


def _loader(descriptor: ApplyPolicy) -> YAML:
    yaml = YAML(typ="rt")
    yaml.version = (1, 1) if descriptor.yaml_version == YamlVersion.V1_1 else (1, 2)
    return yaml


def _parse(text: str, descriptor: ApplyPolicy, label: str, what: str = "") -> Any:
    """The one document of `text` (None when it holds none); refused when it does not parse, holds
    several documents, or is not a mapping at the top."""
    try:
        docs = list(_loader(descriptor).load_all(text))
    except YAMLError as exc:
        raise ApplyRefused(f"{label}{what} does not parse as YAML: {exc}") from exc
    if len(docs) > 1:
        raise ApplyRefused(
            f"{label}{what} holds {len(docs)} YAML documents; the policy goes in one"
        )
    root = docs[0] if docs else None
    if root is not None and not isinstance(root, CommentedMap):
        raise ApplyRefused(f"{label}{what}: the top level is not a mapping")
    if isinstance(root, CommentedMap) and root.fa.flow_style():
        raise ApplyRefused(f"{label}{what}: the top level is a flow mapping, not a block one")
    return root


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


def _value_at(root: Any, path: tuple[str, ...]) -> Any:
    node = root
    for key in path:
        if not isinstance(node, Mapping) or key not in node:
            return None
        node = node[key]
    return node


def _set_plain(tree: dict[str, Any], path: tuple[str, ...], value: list[Any]) -> None:
    node = tree
    for key in path[:-1]:
        child = node.get(key)
        if not isinstance(child, dict):
            child = node[key] = {}
        node = child
    node[path[-1]] = value


# --- text ----------------------------------------------------------------------------------------


def _step(lines: list[str]) -> int:
    """How far the file indents a nested block: the first key whose block is nested, else two."""
    body = [line for line in lines if is_content(line) and not is_marker(line)]
    for here, after in zip(body, body[1:], strict=False):
        if strip_comment(here).endswith(":") and leading_spaces(after) > leading_spaces(here):
            return leading_spaces(after) - leading_spaces(here)
    return DEFAULT_STEP


def _after_key(line: str, col: int, label: str, where: str) -> tuple[str, int]:
    """What follows `key:` on its line, without a trailing comment, and where that text starts."""
    match = _KEY.match(line, col)
    if match is None:
        raise ApplyRefused(f"{label}: cannot read the line holding the key {where}")
    start = match.end()
    rest = strip_comment(line[start:]).strip()
    return rest, start + (len(line[start:]) - len(line[start:].lstrip()))


def _why(rest: str, last: bool) -> str:
    if rest.startswith("["):
        return "written inline as a flow list"
    if rest.startswith("{"):
        return "written as a flow mapping"
    if rest.startswith("*"):
        return "an alias"
    if rest.startswith("&"):
        return "anchored"
    if rest.startswith("!"):
        return "tagged"
    if rest in ("~", "null", "Null", "NULL"):
        return "null"
    return "a single value, not a list" if last else "a single value, not a mapping"


def _reads_as_string(descriptor: ApplyPolicy, value: str) -> bool:
    return _loader(descriptor).resolver.resolve(ScalarNode, value, (True, False)) == STR_TAG


def _plain_safe(descriptor: ApplyPolicy, value: str) -> bool:
    return not (
        not value
        or value != value.strip()
        or value[0] in _INDICATORS
        or ": " in value
        or " #" in value
        or value.endswith(":")
        or "\n" in value
        or "\t" in value
    ) and _reads_as_string(descriptor, value)


def _style_of(line: str, col: int) -> str:
    return {"'": "single", '"': "double"}.get(line[col : col + 1], "plain")


def _quote(descriptor: ApplyPolicy, style: str, value: str) -> str:
    """`value` as a scalar in `style` where that is safe: a plain one the resolver would read as
    something else, or that holds an indicator, is single-quoted."""
    if style == "double":
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if style == "plain" and _plain_safe(descriptor, value):
        return value
    return "'" + value.replace("'", "''") + "'"


# --- where the list is ---------------------------------------------------------------------------


class _Spot(NamedTuple):
    """Where the list at a key path is. `kind` is `block` (a block list; `seq` holds it),
    `flow` (a one-line flow list, only when asked for), `empty` (its key, or a section above it,
    holds nothing; `line` and `col` are that key's), or `missing` (`node` is the deepest mapping
    that exists, `keys` what is absent below it)."""

    kind: str
    keys: tuple[str, ...] = ()
    node: Any = None
    seq: Any = None
    line: int = 0
    col: int = 0
    start: int = 0


def _where(
    root: Any, path: tuple[str, ...], lines: list[str], label: str, *, flow: bool = False
) -> _Spot:
    if root is None:
        return _Spot("missing", keys=path)
    node = root
    for depth, key in enumerate(path):
        last = depth == len(path) - 1
        named = _dotted(path[: depth + 1])
        if key not in node:
            return _Spot("missing", keys=path[depth:], node=node)
        line, col = node.lc.key(key)
        rest, start = _after_key(lines[line], col, label, named)
        value = node[key]
        if rest:
            if last and flow and rest.startswith("[") and isinstance(value, CommentedSeq):
                return _Spot("flow", seq=value, line=line, col=col, start=start)
            raise ApplyRefused(
                f"{label}: {named} is {_why(rest, last)}; write it as a block "
                f"({key}: on its own line, then the entries) and run it again"
            )
        if value is None:
            return _Spot("empty", keys=path[depth + 1 :], line=line, col=col)
        if last:
            if isinstance(value, CommentedSeq):
                return _Spot("block", seq=value, line=line, col=col)
            raise ApplyRefused(f"{label}: {named} is not a list")
        if not isinstance(value, CommentedMap):
            raise ApplyRefused(
                f"{label}: {named} is not a mapping, so {_dotted(path)} cannot be set"
            )
        node = value
    raise AssertionError("an empty key path")


# --- inserting -----------------------------------------------------------------------------------


def _block(indent: int, keys: tuple[str, ...], items: Iterable[str], step: int) -> list[str]:
    out = [" " * (indent + number * step) + f"{key}:" for number, key in enumerate(keys)]
    depth = indent + len(keys) * step
    return out + [" " * depth + "- '" + item.replace("'", "''") + "'" for item in items]


def _splice(
    text: str,
    descriptor: ApplyPolicy,
    path: tuple[str, ...],
    items: tuple[str, ...],
    *,
    replace: bool,
    label: str,
) -> str:
    """`text` with `items` added to the list at `path` (or, with `replace`, made its items), by
    inserting or replacing lines; every other line is untouched. Refuses what it cannot."""
    root = _parse(text, descriptor, label)
    lines = split_lines(text)
    spot = _where(root, path, lines, label, flow=replace)
    if not items:
        return text
    eol = "\r\n" if "\r\n" in text else "\n"
    step = _step(lines)
    if spot.kind == "empty":
        at = spot.line + 1
        while (
            at < len(lines)
            and lines[at].strip().startswith("#")
            and leading_spaces(lines[at]) > spot.col
        ):
            at += 1
        insert_lines(lines, at, _block(spot.col + step, spot.keys, items, step), eol)
    elif spot.kind == "missing":
        if spot.node is None:
            at, indent = len(lines), 0
        else:
            first, last = next(iter(spot.node)), list(spot.node)[-1]
            indent = spot.node.lc.key(first)[1]
            top = spot.node is root
            at = (
                node_end(lines, spot.node.lc.key(last)[0], -1 if top else indent, beside_dash=True)
                + 1
            )
        insert_lines(lines, at, _block(indent, spot.keys, items, step), eol)
    elif spot.kind == "flow":
        line = lines[spot.line]
        closing = _flow_end(line, spot.start)
        if closing is None:
            raise ApplyRefused(f"{label}: {_dotted(path)} is a flow list over several lines")
        shown = ", ".join(_quote(descriptor, "plain", item) for item in items)
        lines[spot.line] = f"{line[: spot.start]}[{shown}]{line[closing + 1 :]}"
    else:
        _splice_block(lines, spot, descriptor, items, replace, eol, label)
    return "".join(lines)


def _splice_block(
    lines: list[str],
    spot: _Spot,
    descriptor: ApplyPolicy,
    items: tuple[str, ...],
    replace: bool,
    eol: str,
    label: str,
) -> None:
    seq = spot.seq
    pick = 0 if replace else len(seq) - 1
    line, col = seq.lc.item(pick)
    prefix = lines[line][:col]
    if not _DASH_PREFIX.fullmatch(prefix):
        raise ApplyRefused(f"{label}: cannot read the layout of the list's entries")
    style = _style_of(lines[line], col)
    last_line = seq.lc.item(len(seq) - 1)[0]
    end = node_end(lines, last_line, leading_spaces(prefix))
    new = [prefix + _quote(descriptor, style, item) for item in items]
    if replace:
        closed = lines[end].endswith("\n")
        lines[line : end + 1] = [entry + eol for entry in new[:-1]] + [
            new[-1] + (eol if closed else "")
        ]
    else:
        insert_lines(lines, end + 1, new, eol)


def _flow_end(line: str, start: int) -> int | None:
    """The index of the `]` that closes the flow list opened at `start`, on this line."""
    quote = ""
    depth = 0
    for index in range(start, len(line)):
        char = line[index]
        if quote:
            if char == quote:
                quote = ""
        elif char in "'\"":
            quote = char
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return index
    return None


# --- the writer ----------------------------------------------------------------------------------


def _merge_yaml(
    text: str,
    descriptor: ApplyPolicy,
    wanted: list[str],
    toolset: tuple[str, ...] | None,
    label: str,
) -> Merged:
    root = _parse(text, descriptor, label)
    held = _value_at(root, descriptor.deny_path)
    added = tuple(
        p for p in dict.fromkeys(wanted) if p not in (held if isinstance(held, list) else ())
    )
    result = _splice(text, descriptor, descriptor.deny_path, added, replace=False, label=label)
    change = None
    expected = _plain(root) if root is not None else {}
    _set_plain(
        expected, descriptor.deny_path, [*(_plain(held) if isinstance(held, list) else []), *added]
    )
    if toolset is not None and descriptor.toolset is not None:
        current = _value_at(root, descriptor.toolset.path)
        before = tuple(str(item) for item in current) if isinstance(current, list) else ()
        if before != toolset:
            result = _splice(
                result, descriptor, descriptor.toolset.path, toolset, replace=True, label=label
            )
            _set_plain(expected, descriptor.toolset.path, list(toolset))
            change = (before, toolset)
        else:
            _set_plain(expected, descriptor.toolset.path, _plain(current))
    if result == text:
        return Merged(text=text, added=(), toolset_change=None)
    if _plain(_parse(result, descriptor, label, " after the merge")) != expected:
        raise ApplyRefused(
            f"{label}: the merge did not produce the original plus the added entries "
            "(a defect in the merge, not in your file); nothing was written"
        )
    return Merged(text=result, added=added, toolset_change=change)


# A writer per format; the table's structural test fails a row naming one without.
WRITERS: dict[ApplyFormat, Writer] = {ApplyFormat.YAML: _merge_yaml}


def resolve_home(descriptor: ApplyPolicy, env_file: Path | None = None) -> Path:
    """The agent's home: the descriptor's variable when set, else its default under the home."""
    named = named_value(descriptor.home_env, env_file)
    return Path(named) if named else Path.home() / descriptor.home_default


def _read(path: Path) -> str | None:
    """The text of the configuration at `path`, or None when there is no such file."""
    return path.read_bytes().decode() if path.is_file() else None


def apply(
    descriptor: ApplyPolicy,
    home: Path,
    extra: Iterable[str] = (),
    toolset: bool = False,
    dry_run: bool = False,
) -> ApplyResult:
    """Merge the recommended patterns, then `extra`, into `<home>/<file>`; raises `ApplyRefused`."""
    path = home / descriptor.file
    if toolset and descriptor.toolset is None:
        raise ApplyRefused(f"{descriptor.file}: this agent's row has no recommended toolset")
    before = _read(path)
    if before is None:
        return ApplyResult(
            path=path,
            status=Status.ABSENT,
            message=(
                f"no configuration at {path}; the agent is not installed or its home is "
                f"elsewhere (set {descriptor.home_env})"
            ),
        )
    wanted_toolset = descriptor.toolset.names if toolset and descriptor.toolset else None
    merged = WRITERS[descriptor.format](
        before, descriptor, patterns(extra=extra), wanted_toolset, str(path)
    )
    if merged.text == before:
        return ApplyResult(
            path=path, status=Status.UNCHANGED, message="already up to date, nothing changed"
        )
    diff = "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            merged.text.splitlines(keepends=True),
            fromfile=str(path),
            tofile=str(path),
        )
    )
    result = ApplyResult(
        path=path,
        status=Status.WOULD_WRITE if dry_run else Status.WRITTEN,
        diff=diff,
        added=merged.added,
        toolset_change=merged.toolset_change,
    )
    if dry_run:
        return result
    return result.model_copy(update={"backup": backup_and_replace(path, merged.text)})


class Held(Frozen):
    """What an agent's configuration holds of the policy: its deny list and its toolset."""

    path: Path
    deny: tuple[str, ...]
    toolset: tuple[str, ...] | None


def held(descriptor: ApplyPolicy, home: Path) -> Held | None:
    """What `<home>/<file>` holds, or None when there is no such file; raises `ApplyRefused`
    when it does not parse or holds the deny list as something else. Reads only."""
    path = home / descriptor.file
    text = _read(path)
    if text is None:
        return None
    root = _parse(text, descriptor, str(path))
    deny = _value_at(root, descriptor.deny_path)
    if deny is not None and not isinstance(deny, list):
        raise ApplyRefused(f"{path}: {_dotted(descriptor.deny_path)} is not a list")
    listed = _value_at(root, descriptor.toolset.path) if descriptor.toolset else None
    return Held(
        path=path,
        deny=tuple(str(item) for item in deny) if isinstance(deny, list) else (),
        toolset=tuple(str(item) for item in listed) if isinstance(listed, list) else None,
    )


def backup_and_replace(path: Path, text: str) -> Path | None:
    """Write `text` over `path`, after copying the original once to `<file>.abk-backup`;
    the backup's path when this call made it, None when one was already there."""
    backup = path.with_name(path.name + BACKUP_SUFFIX)
    made = None
    if not backup.exists():
        shutil.copy2(path, backup)
        made = backup
    _replace(path, text)
    return made


def _replace(path: Path, text: str) -> None:
    """Write `text` over `path` through a temporary beside it, keeping the file's mode."""
    mode = path.stat().st_mode
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(text.encode())
        os.chmod(name, mode & 0o7777)
        os.replace(name, path)
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise
