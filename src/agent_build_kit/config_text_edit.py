"""Setting or removing a split's `hold` in `tests.e2e_splits` of `abk.yaml` (or a repo's own
`tests.e2e_splits`) by editing the file as text, so every comment and every other line stays."""

from __future__ import annotations

import copy
import os
import re
from pathlib import Path
from typing import Any

import yaml

from agent_build_kit.compat_names import old_spelling
from agent_build_kit.config import REST_SPLIT
from agent_build_kit.init.scaffold import block_end, indent_of
from agent_build_kit.model import Frozen, TestTier
from agent_build_kit.runtimes.policy_apply import backup_and_replace

__all__ = ["ConfigTextEditError", "TextEdit", "set_hold"]

_HOLD = "hold"
# The key the splits are written under, and the older name still read as the same setting.
_SPLITS = "e2e_splits"
_OLD_SPLITS = f"{old_spelling(TestTier.E2E_TEST)}_splits"
_NULL_TAG = "tag:yaml.org,2002:null"

_Pair = tuple[yaml.ScalarNode, yaml.Node]


class ConfigTextEditError(ValueError):
    """The file cannot be changed as text; the message gives the reason and nothing was
    written, backup included."""


class TextEdit(Frozen):
    """What an edit did."""

    changed: bool = False
    # The backup this edit made; None when one already existed or nothing was written.
    backup: Path | None = None
    # One line saying what was done, or why nothing was.
    summary: str = ""


def set_hold(path: Path, location: str | None, split: str, value: bool | None) -> TextEdit:
    """Set `hold` of the split entry `split` at `tests.e2e_splits` (`location` None) or at the
    own `tests.e2e_splits` of the repo `location`; `value` None removes the key. `rest` may
    have no entry yet, and a `rest` entry left holding nothing else is removed."""
    try:
        text = path.read_bytes().decode()
    except (OSError, UnicodeDecodeError) as error:
        raise _refuse(path, f"it cannot be read ({error})") from error
    if not os.access(path, os.W_OK):
        raise _refuse(path, "the file is read-only and cannot be written")
    try:
        raw = yaml.safe_load(text)
        root = yaml.compose(text)
    except yaml.YAMLError as error:
        raise _refuse(path, f"the text does not parse as YAML ({error})") from error
    raw = {} if raw is None else raw
    if not isinstance(raw, dict) or not (root is None or isinstance(root, yaml.MappingNode)):
        raise _refuse(path, "the top level is not a mapping")

    eol = "\r\n" if "\r\n" in text else "\n"
    lines = re.findall(r"[^\n]*\n|[^\n]+", text)
    head = ["tests"] if location is None else ["repos", location, "tests"]
    # The file's own spelling of the splits key when it has one, else the current one.
    keys = [*head, _SPLITS]
    chain: list[_Pair] = []
    node = root
    for key in keys:
        found = _pair(path, node, key)
        if found is None and key == _SPLITS:
            found = _pair(path, node, _OLD_SPLITS)
            if found is not None:
                keys = [*head, _OLD_SPLITS]
                key = _OLD_SPLITS
        if found is None:
            break
        _no_marker(path, lines, found[0], key)
        chain.append(found)
        node = _container(path, found[1], key)
    if location is not None and len(chain) < 2:
        raise _refuse(path, f"the repo `{location}` is not in the file")

    splits_raw = _dig(raw, keys)
    if location is not None and not isinstance(splits_raw, dict):
        # A repo with no splits of its own follows the top-level ones; giving it a mapping
        # holding one split would replace every split it inherits.
        raise _refuse(
            path,
            f"the repo `{location}` has no `tests.{_SPLITS}` of its own and follows the "
            f"top-level `tests.{_SPLITS}`; set the hold there, or declare the repo's own "
            "splits first",
        )
    declared = list(splits_raw) if isinstance(splits_raw, dict) else []
    if split != REST_SPLIT and split not in declared:
        where = ".".join(keys)
        names = ", ".join([*declared, REST_SPLIT])
        raise _refuse(path, f"`{split}` is not a split declared at {where}; declared: {names}")

    entry_raw = splits_raw.get(split) if isinstance(splits_raw, dict) else None
    entry = _pair(path, node, split) if len(chain) == len(keys) else None
    if entry is not None and not isinstance(entry_raw, dict):
        raise _refuse(path, f"`{split}` is not a mapping")
    if entry is not None:
        _check_entry(path, text, lines, entry, split)
    held = isinstance(entry_raw, dict) and _HOLD in entry_raw
    if (entry_raw or {}).get(_HOLD) is value and (held or value is None):
        return TextEdit(summary=f"hold of {split} is already {_word(value)}; nothing changed")

    if entry is None:
        assert value is not None
        _create(lines, chain, keys, split, value, eol)
    else:
        _edit_entry(path, lines, entry, split, value, eol)
    verb = f"removed hold of {split}" if value is None else f"set hold of {split} to {_word(value)}"
    return _write(path, "".join(lines), _expected(raw, keys, split, value), verb)


def _word(value: bool | None) -> str:
    return "unset" if value is None else str(value).lower()


def _refuse(path: Path, reason: str) -> ConfigTextEditError:
    return ConfigTextEditError(f"{path}: cannot edit it as text: {reason}")


def _anchored(text: str, first: int, last: int) -> bool:
    """Whether an anchor or alias sits on a line of `first..last` (0-based, inclusive)."""
    return any(
        (isinstance(event, yaml.AliasEvent) or getattr(event, "anchor", None))
        and first <= event.start_mark.line <= last
        for event in yaml.parse(text)
    )


def _pair(path: Path, node: yaml.MappingNode | None, key: str) -> _Pair | None:
    if node is None:
        return None
    found = [(k, v) for k, v in node.value if isinstance(k, yaml.ScalarNode) and k.value == key]
    if len(found) > 1:
        raise _refuse(path, f"it has a duplicate `{key}` key")
    return found[0] if found else None


def _no_marker(path: Path, lines: list[str], key: yaml.ScalarNode, name: str) -> None:
    """Refuse a key whose value opens with an anchor, alias or tag."""
    after = lines[key.end_mark.line][key.end_mark.column :]
    if re.match(r":\s*[&*!]", after):
        raise _refuse(path, f"`{name}` carries an anchor, alias or tag")


def _container(path: Path, value: yaml.Node, key: str) -> yaml.MappingNode | None:
    """The block mapping a key holds; None when it is empty."""
    if isinstance(value, yaml.MappingNode):
        if value.flow_style:
            raise _refuse(
                path, f"`{key}` is a flow-style mapping; only a block mapping can be edited"
            )
        return value
    if isinstance(value, yaml.ScalarNode) and value.tag == _NULL_TAG:
        return None
    raise _refuse(path, f"`{key}` is not a mapping")


def _dig(raw: Any, keys: list[str]) -> Any:
    for key in keys:
        raw = raw.get(key) if isinstance(raw, dict) else None
    return raw


def _insert(lines: list[str], at: int, new: list[str], eol: str) -> None:
    if at > 0 and not lines[at - 1].endswith("\n"):
        lines[at - 1] += eol
    lines[at:at] = [line + eol for line in new]


def _create(
    lines: list[str], chain: list[_Pair], keys: list[str], split: str, value: bool, eol: str
) -> None:
    """Append `<split>: {hold: value}` under the deepest mapping that exists, creating the
    mappings that are missing above it."""
    if chain:
        key, mapping = chain[-1]
        margin = key.start_mark.column
        at = block_end(lines, key.start_mark.line, lambda line: indent_of(line) > margin)
        indent = mapping.start_mark.column if isinstance(mapping, yaml.MappingNode) else margin + 2
    else:
        at, indent = len(lines), 0
    new = [" " * (indent + 2 * i) + f"{name}:" for i, name in enumerate(keys[len(chain) :])]
    new.append(" " * (indent + 2 * len(new)) + f"{split}: {{{_HOLD}: {_word(value)}}}")
    _insert(lines, at, new, eol)


def _check_entry(path: Path, text: str, lines: list[str], entry: _Pair, split: str) -> None:
    """Refuse an entry that carries an anchor or alias."""
    key, _ = entry
    _no_marker(path, lines, key, split)
    first, margin = key.start_mark.line, key.start_mark.column
    end = block_end(lines, first, lambda line: indent_of(line) > margin)
    if _anchored(text, first, end - 1):
        raise _refuse(path, f"`{split}` has an anchor or alias")


def _edit_entry(
    path: Path,
    lines: list[str],
    entry: _Pair,
    split: str,
    value: bool | None,
    eol: str,
) -> None:
    key, body = entry
    if not isinstance(body, yaml.MappingNode):
        raise _refuse(path, f"`{split}` is not a mapping")
    first, margin = key.start_mark.line, key.start_mark.column
    end = block_end(lines, first, lambda line: indent_of(line) > margin)
    held = _pair(path, body, _HOLD)
    if body.flow_style and body.start_mark.line != body.end_mark.line:
        raise _refuse(path, f"`{split}` is a multi-line flow entry")
    if value is None and split == REST_SPLIT and len(body.value) == 1:
        del lines[first:end]
    elif body.flow_style:
        _edit_flow(path, lines, body, held, value)
    elif held is None:
        assert value is not None
        _insert(lines, end, [" " * body.start_mark.column + f"{_HOLD}: {_word(value)}"], eol)
    elif value is None:
        del lines[held[0].start_mark.line : held[1].end_mark.line + 1]
    else:
        _replace(path, lines, held[1], _word(value))


def _replace(path: Path, lines: list[str], node: yaml.Node, new: str) -> None:
    if node.start_mark.line != node.end_mark.line:
        raise _refuse(path, "the value of `hold` spans several lines")
    at = node.start_mark.line
    lines[at] = lines[at][: node.start_mark.column] + new + lines[at][node.end_mark.column :]


def _edit_flow(
    path: Path, lines: list[str], body: yaml.MappingNode, held: _Pair | None, value: bool | None
) -> None:
    at = body.start_mark.line
    line = lines[at]
    pairs = body.value
    if held is not None and value is not None:
        _replace(path, lines, held[1], _word(value))
    elif held is None:
        assert value is not None
        if pairs:
            point, new = pairs[-1][1].end_mark.column, f", {_HOLD}: {_word(value)}"
        else:
            point, new = body.start_mark.column + 1, f"{_HOLD}: {_word(value)}"
        lines[at] = line[:point] + new + line[point:]
    else:
        assert held is not None
        index = next(i for i, (k, _) in enumerate(pairs) if k is held[0])
        if index + 1 < len(pairs):
            start, stop = held[0].start_mark.column, pairs[index + 1][0].start_mark.column
        elif index > 0:
            start, stop = pairs[index - 1][1].end_mark.column, held[1].end_mark.column
        else:
            start, stop = held[0].start_mark.column, held[1].end_mark.column
        lines[at] = line[:start] + line[stop:]


def _expected(raw: dict[str, Any], keys: list[str], split: str, value: bool | None) -> object:
    """The document the edit must reload to."""
    expected = copy.deepcopy(raw)
    mapping = expected
    for key in keys:
        child = mapping.get(key) or {}
        mapping[key] = child
        mapping = child
    entry = mapping.get(split) or {}
    if value is None:
        entry.pop(_HOLD, None)
        if split == REST_SPLIT and not entry:
            del mapping[split]
    else:
        entry[_HOLD] = value
        mapping[split] = entry
    return expected


def _write(path: Path, updated: str, expected: object, summary: str) -> TextEdit:
    try:
        reloaded: Any = yaml.safe_load(updated)
    except yaml.YAMLError:
        reloaded = None
    if reloaded != expected:
        raise _refuse(path, "the edit did not give the expected hold; nothing was written")
    try:
        backup = backup_and_replace(path, updated)
    except OSError as error:
        raise _refuse(path, f"it cannot be written ({error})") from error
    return TextEdit(changed=True, backup=backup, summary=f"{summary} in {path}")
