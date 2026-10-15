"""Adding a runtime to or removing it from `tests.runtimes_blocked` and `tests.runtimes_allowed`
in `abk.yaml` by editing the file as text, so every comment and every other line stays."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

from agent_build_kit.init.scaffold import block_end, child_indent, indent_of
from agent_build_kit.model import Frozen
from agent_build_kit.runtimes.policy_apply import backup_and_replace

__all__ = ["ConfigTextEditError", "TextEdit", "add_runtime", "remove_runtime"]

_TESTS_KEY = re.compile(r"^['\"]?tests['\"]?\s*:(?P<rest>.*)$")
_ITEM = re.compile(r"^(?P<indent>\s*)-(?:\s+(?P<value>.*))?$")
_COMMENT = re.compile(r"\s+#.*$")


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


def add_runtime(path: Path, setting: str, name: str) -> TextEdit:
    """Add `name` to `tests.<setting>` of the abk.yaml at `path`; already there, nothing changes."""
    return _edit(path, setting, name, add=True)


def remove_runtime(path: Path, setting: str, name: str) -> TextEdit:
    """Remove `name` from `tests.<setting>` of the abk.yaml at `path`; absent, nothing changes."""
    return _edit(path, setting, name, add=False)


def _content(line: str) -> str:
    return line.rstrip("\r\n")


def _bare(value: str) -> str:
    return _COMMENT.sub("", value).strip().strip("'\"")


def _refuse(path: Path, reason: str) -> ConfigTextEditError:
    return ConfigTextEditError(f"{path}: cannot edit it as text: {reason}")


def _anchored(text: str, first: int, last: int) -> bool:
    """Whether an anchor or alias sits on a line of `first..last` (0-based, inclusive)."""
    return any(
        (isinstance(event, yaml.AliasEvent) or getattr(event, "anchor", None))
        and first <= event.start_mark.line <= last
        for event in yaml.parse(text)
    )


def _edit(path: Path, setting: str, name: str, *, add: bool) -> TextEdit:
    try:
        text = path.read_bytes().decode()
    except (OSError, UnicodeDecodeError) as error:
        raise _refuse(path, f"it cannot be read ({error})") from error
    if not os.access(path, os.W_OK):
        raise _refuse(path, "the file is read-only and cannot be written")
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise _refuse(path, f"the text does not parse as YAML ({error})") from error
    raw = {} if raw is None else raw
    if not isinstance(raw, dict):
        raise _refuse(path, "the top level is not a mapping")

    eol = "\r\n" if "\r\n" in text else "\n"
    lines = re.findall(r"[^\n]*\n|[^\n]+", text)
    tops = [i for i, line in enumerate(lines) if _TESTS_KEY.match(_content(line))]
    if len(tops) > 1:
        raise _refuse(path, "it has a duplicate `tests` key")

    unchanged = f"{name} is {'already in' if add else 'not in'} tests.{setting}; nothing changed"
    if not tops:
        if not add:
            return TextEdit(summary=unchanged)
        head = text if not text or text.endswith("\n") else text + eol
        updated = head + eol.join(["tests:", f"  {setting}: [{name}]", ""])
        return _write(path, updated, {**raw, "tests": {setting: [name]}}, f"added {name}")

    top = tops[0]
    opening = _TESTS_KEY.match(_content(lines[top]))
    inline = opening.group("rest").strip() if opening else ""
    if inline and not inline.startswith("#"):
        if inline.startswith(("&", "*")):
            raise _refuse(path, "`tests` carries an anchor or alias")
        if inline.startswith("!"):
            raise _refuse(path, "`tests` carries a tag")
        kind = "a flow-style mapping" if inline.startswith("{") else "not a mapping"
        raise _refuse(path, f"`tests` is {kind}; only a block mapping can be edited")
    tests = raw.get("tests")
    if tests is not None and not isinstance(tests, dict):
        raise _refuse(path, "`tests` is not a mapping")
    end = block_end(lines, top, lambda line: indent_of(line) > 0)
    if _anchored(text, top, end - 1):
        raise _refuse(path, "the `tests` block has an anchor or alias")

    indent = len(child_indent(lines, top, 0))
    key = re.compile("^" + " " * indent + "(['\"]?)" + re.escape(setting) + r"\1:(?P<rest>.*)$")
    found = [i for i in range(top + 1, end) if key.match(_content(lines[i]))]
    if len(found) > 1:
        raise _refuse(path, f"`tests` has a duplicate `{setting}` key")
    tests = tests or {}
    if found and not isinstance(tests.get(setting), list):
        raise _refuse(path, f"`tests.{setting}` is not a list")

    if not found:
        if not add:
            return TextEdit(summary=unchanged)
        if not lines[end - 1].endswith("\n"):
            lines[end - 1] += eol
        lines.insert(end, " " * indent + f"{setting}: [{name}]" + eol)
        expected = {**raw, "tests": {**tests, setting: [name]}}
        return _write(path, "".join(lines), expected, f"added {name}")

    at = found[0]
    current = tests[setting]
    after = key.match(_content(lines[at]))
    after = after.group("rest") if after else ""
    flow = bool(after.strip()) and not after.strip().startswith("#")
    if flow and "]" not in after:
        raise _refuse(path, "the list is a multi-line flow list")
    if (name in current) == add:
        return TextEdit(summary=unchanged)
    if flow:
        lines[at] = _flow(path, lines[at], after, name, add=add)
    else:
        _block_list(lines, at, end, indent, name, add=add, eol=eol)
    updated = [*current, name] if add else [item for item in current if item != name]
    expected = {**raw, "tests": {**tests, setting: updated}}
    return _write(path, "".join(lines), expected, f"{'added' if add else 'removed'} {name}")


def _flow(path: Path, line: str, after: str, name: str, *, add: bool) -> str:
    opened = after.find("[")
    closed = after.find("]")
    if opened < 0 or after[:opened].strip():
        raise _refuse(path, "the value is not a list")
    if closed < 0:
        raise _refuse(path, "the list is a multi-line flow list")
    items = [item.strip() for item in after[opened + 1 : closed].split(",") if item.strip()]
    if add:
        quote = items[0][0] if items and items[0][0] in "'\"" else ""
        items.append(f"{quote}{name}{quote}")
    else:
        items = [item for item in items if item.strip("'\"") != name]
    body = _content(line)
    head = body[: len(body) - len(after)]
    return f"{head}{after[: opened + 1]}{', '.join(items)}{after[closed:]}{line[len(body) :]}"


def _block_list(
    lines: list[str], at: int, end: int, indent: int, name: str, *, add: bool, eol: str
) -> None:
    items: list[tuple[int, str]] = []
    for index in range(at + 1, end):
        body = _content(lines[index])
        if not body.strip() or body.strip().startswith("#"):
            continue
        item = _ITEM.match(body)
        if item is None or len(item.group("indent")) < indent:
            break
        items.append((index, item.group("value") or ""))
    if add:
        last, value = items[-1]
        quote = value[0] if value[:1] in ("'", '"') else ""
        prefix = lines[last][: indent_of(lines[last])]
        if not lines[last].endswith("\n"):
            lines[last] += eol
        lines.insert(last + 1, f"{prefix}- {quote}{name}{quote}{eol}")
        return
    doomed = [index for index, value in items if _bare(value) == name]
    if len(doomed) == len(items):
        key_text = _content(lines[at])
        comment = _COMMENT.search(key_text)
        head = key_text[: comment.start()] if comment else key_text
        lines[at] = f"{head} []{comment.group(0) if comment else ''}{eol}"
    for index in reversed(doomed):
        del lines[index]


def _write(path: Path, updated: str, expected: object, summary: str) -> TextEdit:
    try:
        reloaded: Any = yaml.safe_load(updated)
    except yaml.YAMLError:
        reloaded = None
    if reloaded != expected:
        raise _refuse(path, "the edit did not give the expected lists; nothing was written")
    try:
        backup = backup_and_replace(path, updated)
    except OSError as error:
        raise _refuse(path, f"it cannot be written ({error})") from error
    return TextEdit(changed=True, backup=backup, summary=f"{summary} in {path}")
