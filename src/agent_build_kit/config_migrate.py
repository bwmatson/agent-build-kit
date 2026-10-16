"""Moving an abk.yaml from `limits` to `global_limits` and `project_limits` by editing its text
(spec: limits-split-into-global-and-project).

The parse finds the block and the lines of the moved settings; the lines are then edited with the
helpers `abk policy apply` uses, so every other byte of the file is as it was. The document is
never dumped. The new text is parsed and compared with the old document, renamed and moved in
memory, before it is returned."""

from __future__ import annotations

import re
from typing import Any

import yaml

from agent_build_kit.config import DEPRECATED_ROOT_KEY
from agent_build_kit.model import Frozen
from agent_build_kit.runtimes.policy_apply import (
    _end,
    _insert,
    _lines,
    _strip_comment,
)

__all__ = ["ConfigMigrateError", "Migrated", "migrate"]

GLOBAL = "global_limits"
PROJECT = "project_limits"
MOVED = ("max_units_in_progress", "max_concurrent_stacks", "max_concurrent_restacks")
_NULL_TAG = "tag:yaml.org,2002:null"
_MERGE_TAG = "tag:yaml.org,2002:merge"
_MARKED = re.compile(r"(?:^|[\s:])[&*][\w-]")


class ConfigMigrateError(ValueError):
    """The text cannot be migrated as text; the message names the key and the reason."""


class Migrated(Frozen):
    """The new text, and the settings moved to `project_limits` (empty when nothing moved)."""

    text: str
    moved: tuple[str, ...] = ()


def _refuse(key: str, reason: str) -> ConfigMigrateError:
    return ConfigMigrateError(f"{key}: {reason}")


def _pair(root: yaml.MappingNode, name: str) -> tuple[yaml.ScalarNode, yaml.Node] | None:
    for key, value in root.value:
        if isinstance(key, yaml.ScalarNode) and key.value == name:
            return key, value
    return None


def _region(lines: list[str], key_line: int, block_line: int) -> tuple[int, int]:
    """The first and last line of a moved setting: its own line and the comment lines directly
    above it, which are taken to be about it."""
    first = key_line
    while first - 1 > block_line and lines[first - 1].strip().startswith("#"):
        first -= 1
    return first, key_line


def _check_line(lines: list[str], key: yaml.ScalarNode, value: yaml.Node) -> None:
    name = key.value
    line = key.start_mark.line
    if value.start_mark.line != line or value.end_mark.line != line:
        raise _refuse(name, "its value is on more than one line, which cannot be moved by lines")
    if _MARKED.search(_strip_comment(lines[line])):
        raise _refuse(name, "it has an anchor or an alias, which cannot be moved by lines")


def _expected(old: dict[str, Any], source: str) -> dict[str, Any]:
    block = dict(old[source] or {})
    unset = old[source] is None
    moved = {name: block.pop(name) for name in MOVED if name in block}
    renamed = {GLOBAL if key == source else key: value for key, value in old.items()}
    renamed[GLOBAL] = None if unset and not moved else block
    if moved:
        renamed[PROJECT] = moved
    return renamed


def migrate(text: str) -> Migrated:
    """Rename a root `limits` to `global_limits` and move the three scheduling settings found
    under it (or under `global_limits`) to a `project_limits` block straight after it."""
    try:
        documents = list(yaml.compose_all(text))
    except yaml.YAMLError as error:
        raise _refuse("abk.yaml", f"the text does not parse as YAML ({error})") from error
    if len(documents) > 1:
        raise _refuse("abk.yaml", "the file holds several documents, and only one can be edited")
    root = documents[0] if documents else None
    if not isinstance(root, yaml.MappingNode):
        return Migrated(text=text)

    old_pair, new_pair = _pair(root, DEPRECATED_ROOT_KEY), _pair(root, GLOBAL)
    if old_pair and new_pair:
        raise _refuse(
            f"{DEPRECATED_ROOT_KEY} and {GLOBAL}",
            "both are set, keep one of them before the settings can be moved",
        )
    found = old_pair or new_pair
    if found is None:
        return Migrated(text=text)
    block_key, block = found
    if isinstance(block, yaml.ScalarNode):
        if block.tag != _NULL_TAG:
            raise _refuse(block_key.value, "the block is not a mapping of settings")
        pairs: list[tuple[yaml.Node, yaml.Node]] = []
    elif isinstance(block, yaml.MappingNode):
        pairs = list(block.value)
    else:
        raise _refuse(block_key.value, "the block is not a mapping of settings")
    if any(key.tag == _MERGE_TAG for key, _ in pairs):
        raise _refuse(block_key.value, "the block uses a merge key, which cannot be moved by lines")

    moving = [
        (key, value)
        for key, value in pairs
        if isinstance(key, yaml.ScalarNode) and key.value in MOVED
    ]
    renaming = block_key.value == DEPRECATED_ROOT_KEY
    if not moving and not renaming:
        return Migrated(text=text)

    held = _pair(root, PROJECT)
    if held is not None and moving:
        present = held[1].value if isinstance(held[1], yaml.MappingNode) else []
        for key, _ in present:
            if isinstance(key, yaml.ScalarNode) and key.value in {k.value for k, _ in moving}:
                raise _refuse(key.value, f"it is already set in {PROJECT}")
        raise _refuse(PROJECT, f"{PROJECT} is already set, move the settings into it by hand")
    if moving and isinstance(block, yaml.CollectionNode) and block.flow_style:
        raise _refuse(
            block_key.value, "a flow-style block cannot be edited without rewriting the line"
        )

    lines = _lines(text)
    eol = "\r\n" if "\r\n" in text else "\n"
    block_line, col = block_key.start_mark.line, block_key.start_mark.column
    regions = []
    for key, value in moving:
        assert isinstance(key, yaml.ScalarNode)
        _check_line(lines, key, value)
        regions.append(_region(lines, key.start_mark.line, block_line))
    carried = [line.rstrip("\r\n") for first, last in regions for line in lines[first : last + 1]]
    for first, last in reversed(regions):
        del lines[first : last + 1]

    leaving = {key.value for key, _ in moving}
    left = [
        key for key, _ in pairs if isinstance(key, yaml.ScalarNode) and key.value not in leaving
    ]
    lines[block_line] = _renamed(lines[block_line], block_key, empty=not left)
    if moving:
        at = _end(lines, block_line, col) + 1
        _insert(lines, at, [" " * col + f"{PROJECT}:", *carried], eol)

    result = "".join(lines)
    if not text.endswith("\n"):
        result = result.removesuffix("\n").removesuffix("\r")
    _verify(text, result, block_key.value)
    return Migrated(text=result, moved=tuple(key.value for key, _ in moving))


def _renamed(line: str, key: yaml.ScalarNode, *, empty: bool) -> str:
    """The key's line under its new name, reading `{}` when nothing is left under it."""
    start = line.index(key.value, key.start_mark.column)
    end = start + len(key.value)
    name = GLOBAL if key.value == DEPRECATED_ROOT_KEY else key.value
    head, tail = line[:start] + name, line[end:]
    if empty:
        colon = tail.index(":") + 1
        rest = tail[colon:]
        if not _strip_comment(rest).strip():
            tail = tail[:colon] + " {}" + rest
    return head + tail


def _verify(text: str, result: str, source: str) -> None:
    try:
        new = yaml.safe_load(result)
        old = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise _refuse(source, f"the edited text would not parse ({error})") from error
    if new != _expected(old, source):
        raise _refuse(source, "the edited text would differ from the file in more than the move")
