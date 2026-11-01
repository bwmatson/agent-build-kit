"""Moving the machine settings of a tracked abk.yaml into abk.local.yaml, by editing both texts
as lines (spec: config-migration). The settings come from the table in `machine_settings`."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

from agent_build_kit.config import (
    DEPRECATED_USAGE_LIMITS,
    USAGE_LIMITS,
    alias_runtimes_usage_limits,
    merge_local,
)
from agent_build_kit.config_migrate_lines import (
    MARKED,
    ConfigMigrateError,
    joined,
    opened,
    pair,
    refuse,
    region,
    shifted,
)
from agent_build_kit.machine_settings import MachineSetting, machine_settings
from agent_build_kit.model import Frozen
from agent_build_kit.yaml_lines import insert_lines, node_end, split_lines, strip_comment

__all__ = [
    "Conflict",
    "MachineMove",
    "MachineRequest",
    "check_move",
    "move_machine_settings",
]

TRACKED = "abk.yaml"
LOCAL = "abk.local.yaml"
_FRESH_STEP = 2

SettingPath = tuple[str, ...]


class MachineRequest(Frozen):
    """What the caller decides: the git top level and the directory a repo path is resolved from
    (default the top level), the local file's text (None when there is no file) and whether the
    fine-to-commit defaults of the table move too."""

    toplevel: Path
    root: Path | None = None
    local_text: str | None = None
    include_defaults: bool = False


class Conflict(Frozen):
    """A setting left in abk.yaml, and the path abk.local.yaml already sets that stops it."""

    path: SettingPath
    local_path: SettingPath


class MachineMove(Frozen):
    """The new text of each file, the paths moved and the settings left."""

    text: str
    local_text: str | None
    moved: tuple[SettingPath, ...] = ()
    conflicts: tuple[Conflict, ...] = ()


def _dotted(path: SettingPath) -> str:
    return ".".join(path)


def _ending(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def _opened_in(
    file: str, lines: list[str], key: yaml.ScalarNode, value: yaml.Node, dotted: str, name: str
) -> None:
    try:
        opened(lines, key, value, dotted, name)
    except ConfigMigrateError as error:
        raise ConfigMigrateError(f"{error} ({file})") from error


def _local_mapping(local_text: str | None, dotted: str) -> dict[str, Any]:
    """The settings the local text holds; a text that cannot be edited as one is refused."""
    if local_text is None:
        return {}
    try:
        documents = list(yaml.compose_all(local_text))
        loaded = yaml.safe_load(local_text) if len(documents) <= 1 else None
    except yaml.YAMLError as error:
        raise refuse(dotted, f"{LOCAL} does not parse as YAML ({error})") from error
    if len(documents) > 1:
        raise refuse(dotted, f"{LOCAL} holds several documents, and only one can be edited")
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise refuse(dotted, f"{LOCAL} is not a mapping of settings")
    return loaded


def _aliased(local: dict[str, Any], dotted: str) -> dict[str, Any]:
    """The local settings with the old `limits` key read as `usage_limits`, as the loader reads
    them, so a setting moved there is not set twice."""
    try:
        return alias_runtimes_usage_limits(local)
    except ValueError as error:
        raise refuse(dotted, f"{LOCAL}: {error}") from error


def _written(local: dict[str, Any], path: SettingPath) -> SettingPath:
    """`path` with `usage_limits` spelled `limits` where the local file spells it so."""
    current: Any = local
    spelled = []
    for name in path:
        if (
            isinstance(current, dict)
            and name == USAGE_LIMITS
            and name not in current
            and DEPRECATED_USAGE_LIMITS in current
        ):
            name = DEPRECATED_USAGE_LIMITS
        spelled.append(name)
        current = current.get(name) if isinstance(current, dict) else None
    return tuple(spelled)


def _conflict(local: dict[str, Any], path: SettingPath) -> SettingPath | None:
    """The path the local settings set that stops `path` from moving, or None."""
    current: Any = local
    for index, name in enumerate(path):
        if not isinstance(current, dict) or name not in current:
            return None
        value = current[name]
        if index == len(path) - 1:
            if isinstance(value, dict) and value:
                return (*path, str(next(iter(value))))
            return path
        if not isinstance(value, dict):
            return path[: index + 1]
        current = value
    return None


def _chain(
    lines: list[str], root: yaml.MappingNode, path: SettingPath
) -> list[tuple[yaml.ScalarNode, yaml.Node]]:
    """The written key and value of each step of `path`; a step that is not written as a key of
    its own, or that lines cannot edit, is refused."""
    dotted = _dotted(path)
    chain: list[tuple[yaml.ScalarNode, yaml.Node]] = []
    node: yaml.Node = root
    for index, name in enumerate(path):
        found = pair(node, name) if isinstance(node, yaml.MappingNode) else None
        if found is None:
            raise refuse(
                dotted,
                f"{TRACKED} does not write it as a key of its own (a merge key or an alias "
                "brings it in), so it cannot be moved by lines",
            )
        chain.append(found)
        if index < len(path) - 1:
            _opened_in(TRACKED, lines, *found, dotted, name)
        node = found[1]
    value = chain[-1][1]
    spans = value.start_mark.line != value.end_mark.line
    if isinstance(value, yaml.CollectionNode) and value.flow_style and spans:
        raise refuse(dotted, f"{TRACKED}: its flow-style value spans lines")
    return chain


def _braced(line: str, key: yaml.ScalarNode) -> str:
    """The parent's line reading `{}` after its colon, its end-of-line comment kept."""
    colon = line.index(":", key.start_mark.column + len(key.value)) + 1
    return line[:colon] + " {}" + line[colon:]


def _lift(
    text: str, root: yaml.MappingNode, movable: list[MachineSetting]
) -> tuple[str, list[tuple[SettingPath, list[str], int]]]:
    """The tracked text without the settings, and the lines each carried with the column of its
    key."""
    lines = split_lines(text)
    carried: list[tuple[SettingPath, list[str], int]] = []
    regions: list[tuple[int, int]] = []
    parents: dict[int, list[Any]] = {}
    for setting in movable:
        chain = _chain(lines, root, setting.path)
        key = chain[-1][0]
        before = chain[-2][0].start_mark.line if len(chain) > 1 else -1
        first, _ = region(lines, key.start_mark.line, before)
        last = node_end(lines, key.start_mark.line, key.start_mark.column, beside_dash=True)
        if any(MARKED.search(strip_comment(line)) for line in lines[first : last + 1]):
            raise refuse(
                _dotted(setting.path),
                f"{TRACKED}: it has an anchor or an alias, which cannot be moved by lines",
            )
        if len(chain) > 1:
            held = parents.setdefault(id(chain[-2][1]), [*chain[-2], 0])
            held[2] += 1
        carried.append((setting.path, lines[first : last + 1], key.start_mark.column))
        regions.append((first, last))
    for key, value, count in parents.values():
        if count == len(value.value):
            lines[key.start_mark.line] = _braced(lines[key.start_mark.line], key)
    for first, last in sorted(regions, reverse=True):
        del lines[first : last + 1]
    return joined(lines, text), carried


def _place(lines: list[str], path: SettingPath, body: list[str], column: int, eol: str) -> None:
    """Insert the carried `body` of the setting at `path` into the local `lines`, under the
    deepest ancestor the local text already writes, with the keys it lacks written above it."""
    dotted = _dotted(path)
    documents = list(yaml.compose_all("".join(lines)))
    root = documents[0] if documents else None
    at, col, step, existing = len(lines), 0, _FRESH_STEP, 0
    if isinstance(root, yaml.MappingNode):
        if root.flow_style:
            raise refuse(dotted, f"{LOCAL} is flow-style, which cannot be edited by lines")
        col = root.value[0][0].start_mark.column
        for first_key, first_value in root.value:
            if isinstance(first_value, yaml.MappingNode) and first_value.value:
                step = first_value.value[0][0].start_mark.column - first_key.start_mark.column
                break
        node = root
        for name in path[:-1]:
            found = pair(node, name)
            if found is None:
                break
            key, value = found
            _opened_in(LOCAL, lines, key, value, dotted, name)
            if not isinstance(value, yaml.MappingNode):
                raise refuse(dotted, f"{LOCAL}: {name} is not a mapping of settings")
            existing += 1
            node = value
            at = node_end(lines, key.start_mark.line, key.start_mark.column) + 1
            col = value.value[0][0].start_mark.column
            step = col - key.start_mark.column
    fresh = path[existing:-1]
    headers = [" " * (col + step * depth) + name + ":" for depth, name in enumerate(fresh)]
    leaf = col + step * len(fresh)
    insert_lines(lines, at, [*headers, *shifted(body, leaf - column)], eol)


def move_machine_settings(text: str, request: MachineRequest) -> MachineMove:
    """Move each machine setting of `text` that the local file does not set to the local file.
    The files are edited by lines, so every other byte stays; what lines cannot edit is refused,
    and a setting the local file sets is left and reported."""
    try:
        documents = list(yaml.compose_all(text))
    except yaml.YAMLError as error:
        raise refuse(TRACKED, f"{TRACKED} does not parse as YAML ({error})") from error
    if len(documents) > 1:
        raise refuse(TRACKED, f"{TRACKED} holds several documents, and only one can be edited")
    root = documents[0] if documents else None
    unchanged = MachineMove(text=text, local_text=request.local_text)
    if not isinstance(root, yaml.MappingNode):
        return unchanged
    settings = [
        setting
        for setting in machine_settings(yaml.safe_load(text), request.toplevel, request.root)
        if request.include_defaults or setting.kind == "machine"
    ]
    if not settings:
        return unchanged
    dotted = _dotted(settings[0].path)
    local = _local_mapping(request.local_text, dotted)
    aliased = _aliased(local, dotted)
    conflicts: list[Conflict] = []
    movable: list[MachineSetting] = []
    for setting in settings:
        stopped = _conflict(aliased, setting.path)
        if stopped is None:
            movable.append(setting)
        else:
            conflicts.append(Conflict(path=setting.path, local_path=_written(local, stopped)))
    if not movable:
        return unchanged.model_copy(update={"conflicts": tuple(conflicts)})
    new_text, carried = _lift(text, root, movable)
    own = request.local_text or ""
    # An existing local file keeps its own line ending; a new one takes the tracked file's.
    eol = ("\r\n" if "\r\n" in own else "\n") if "\n" in own else _ending(text)
    local_lines = split_lines(request.local_text or "")
    for path, body, column in carried:
        _place(local_lines, path, body, column, eol)
    new_local = "".join(local_lines)
    moved = tuple(setting.path for setting in movable)
    check_move(text, request.local_text, new_text, new_local, moved)
    return MachineMove(text=new_text, local_text=new_local, moved=moved, conflicts=tuple(conflicts))


def _load(text: str | None, file: str) -> dict[str, Any]:
    try:
        loaded = yaml.safe_load(text or "")
    except yaml.YAMLError as error:
        raise refuse(file, f"the new text would not parse ({error})") from error
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise refuse(file, "the new text would not be a mapping of settings")
    return loaded


def _first_difference(
    a: dict[str, Any], b: dict[str, Any], prefix: SettingPath = ()
) -> SettingPath:
    for key in dict.fromkeys([*a, *b]):
        if key in a and key in b and a[key] == b[key]:
            continue
        if key in a and key in b and isinstance(a[key], dict) and isinstance(b[key], dict):
            return _first_difference(a[key], b[key], (*prefix, str(key)))
        return (*prefix, str(key))
    return prefix


def _without(document: dict[str, Any], moved: tuple[SettingPath, ...]) -> dict[str, Any]:
    result = copy.deepcopy(document)
    for path in moved:
        parent: Any = result
        for name in path[:-1]:
            parent = parent.get(name) if isinstance(parent, dict) else None
        if isinstance(parent, dict):
            parent.pop(path[-1], None)
    return result


def _with(
    local: dict[str, Any], moved: tuple[SettingPath, ...], base: dict[str, Any]
) -> dict[str, Any]:
    result = copy.deepcopy(local)
    for path in moved:
        value: Any = base
        for name in path:
            value = value[name]
        parent = result
        for name in path[:-1]:
            parent = parent.setdefault(name, {})
        parent[path[-1]] = copy.deepcopy(value)
    return result


def check_move(
    old_text: str,
    old_local: str | None,
    new_text: str,
    new_local: str | None,
    moved: tuple[SettingPath, ...],
) -> None:
    """Refuse, naming the first differing key, a move whose merged configuration differs or
    whose texts differ from the old ones by more than the moved paths."""
    old_base, old_loc = _load(old_text, TRACKED), _load(old_local, LOCAL)
    new_base, new_loc = _load(new_text, TRACKED), _load(new_local, LOCAL)
    before, after = merge_local(old_base, old_loc), merge_local(new_base, new_loc)
    if before != after:
        raise refuse(
            _dotted(_first_difference(before, after)),
            "the move would change the merged configuration",
        )
    for file, wanted, got in (
        (TRACKED, _without(old_base, moved), new_base),
        (LOCAL, _with(old_loc, moved, old_base), new_loc),
    ):
        if wanted != got:
            raise refuse(
                _dotted(_first_difference(wanted, got)),
                f"{file} would differ from the file in more than the moved settings",
            )
