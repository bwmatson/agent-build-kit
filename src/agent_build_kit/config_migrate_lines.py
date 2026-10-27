"""The line-edit helpers the abk.yaml migrations share: the refusal, a key's pair in a composed
mapping, the lines a moved setting owns, and the checks of a block that lines can be edited in."""

from __future__ import annotations

import re

import yaml

from agent_build_kit.yaml_lines import leading_spaces, strip_comment

__all__ = [
    "ConfigMigrateError",
    "MARKED",
    "MERGE_TAG",
    "joined",
    "opened",
    "pair",
    "refuse",
    "region",
    "rename_on_line",
    "shifted",
]

MERGE_TAG = "tag:yaml.org,2002:merge"
MARKED = re.compile(r"(?:^|[\s:])[&*][\w-]")


class ConfigMigrateError(ValueError):
    """The text cannot be migrated as text; the message names the key and the reason."""


def refuse(key: str, reason: str) -> ConfigMigrateError:
    return ConfigMigrateError(f"{key}: {reason}")


def pair(root: yaml.MappingNode, name: str) -> tuple[yaml.ScalarNode, yaml.Node] | None:
    for key, value in root.value:
        if isinstance(key, yaml.ScalarNode) and key.value == name:
            return key, value
    return None


def region(lines: list[str], key_line: int, block_line: int) -> tuple[int, int]:
    """The first and last line of a moved setting: its own line and the comment lines directly
    above it, which are taken to be about it."""
    first = key_line
    while first - 1 > block_line and lines[first - 1].strip().startswith("#"):
        first -= 1
    return first, key_line


def opened(
    lines: list[str], key: yaml.ScalarNode, value: yaml.Node, as_key: str, name: str
) -> None:
    """Refuse, naming `as_key`, a block the lines under `key` cannot be edited in: one with an
    anchor or alias on its key's line, a flow style or a merge key."""
    if MARKED.search(strip_comment(lines[key.start_mark.line])):
        raise refuse(as_key, f"{name} has an anchor or an alias, which cannot be edited by lines")
    if isinstance(value, yaml.CollectionNode) and value.flow_style:
        raise refuse(as_key, f"{name} is flow-style, which cannot be edited by lines")
    if isinstance(value, yaml.MappingNode) and any(k.tag == MERGE_TAG for k, _ in value.value):
        raise refuse(as_key, f"{name} uses a merge key, which cannot be edited by lines")


def rename_on_line(
    lines: list[str], key: yaml.ScalarNode, old: str, new: str, as_key: str
) -> None:
    """Rename the key `old` to `new` on its own line, in place; refuse, naming `as_key`, a key
    with an anchor or an alias on its line, or one that is quoted or written across lines."""
    line, col = key.start_mark.line, key.start_mark.column
    if MARKED.search(strip_comment(lines[line])):
        raise refuse(as_key, "it has an anchor or an alias, which cannot be edited")
    if lines[line][col : col + len(old)] != old:
        raise refuse(as_key, "it is quoted or written across lines, so it is not renamed")
    lines[line] = lines[line][:col] + new + lines[line][col + len(old) :]


def joined(lines: list[str], text: str) -> str:
    """The edited lines as text, ending as `text` did: a final newline is not added."""
    result = "".join(lines)
    if not text.endswith("\n"):
        result = result.removesuffix("\n").removesuffix("\r")
    return result


def shifted(lines: list[str], by: int) -> list[str]:
    """`lines` without their endings, each non-blank one indented `by` more spaces (fewer if
    negative)."""
    out = []
    for line in lines:
        text = line.rstrip("\r\n")
        if text.strip():
            text = " " * by + text if by >= 0 else text[min(-by, leading_spaces(text)) :]
        out.append(text)
    return out
