"""Moving an abk.yaml from `limits` to `global_limits` and `project_limits`, renaming its old
test-kind setting keys and moving `max_unit_lines` to `review.ceilings.full`, by editing its text
(specs: limits-split-into-global-and-project, open-changes-are-migrated-to-review-tiers and
units-are-sized-by-review-tier).

The parse finds the block and the lines of the moved settings; the lines are then edited with the
helpers `abk policy apply` uses, so every other byte of the file is as it was. The document is
never dumped. The new text is parsed and compared with the old document, renamed and moved in
memory, before it is returned."""

from __future__ import annotations

import re
from typing import Any

import yaml

from agent_build_kit.compat_names import Place, new_spelling
from agent_build_kit.config import (
    BUILDERS_KEY,
    DEPRECATED_BUILDERS_KEY,
    DEPRECATED_ROOT_KEY,
    DEPRECATED_USAGE_LIMITS,
    USAGE_LIMITS,
    WorkspaceConfig,
    alias_usage_limits,
    old_setting_blocks,
    read_new_settings,
)
from agent_build_kit.config_migrate_lines import (
    MARKED,
    MERGE_TAG,
    ConfigMigrateError,
    joined,
    opened,
    pair,
    refuse,
    region,
    shifted,
)
from agent_build_kit.config_migrate_machine import (
    Conflict,
    MachineRequest,
    move_machine_settings,
)
from agent_build_kit.model import Frozen
from agent_build_kit.runtimes import DEFAULT as DEFAULT_RUNTIME
from agent_build_kit.yaml_lines import insert_lines, node_end, split_lines, strip_comment

__all__ = ["ConfigMigrateError", "Migrated", "migrate"]

GLOBAL = "global_limits"
PROJECT = "project_limits"
MOVED = ("max_units_in_progress", "max_concurrent_stacks", "max_concurrent_restacks")
CEILING_KEY = "max_unit_lines"
REVIEW = "review"
CEILINGS = "ceilings"
FULL = "full"
MODELS = "models"
RUNTIMES = "runtimes"
_NULL_TAG = "tag:yaml.org,2002:null"


class Migrated(Frozen):
    """The new text, and the settings moved to `project_limits` (empty when nothing moved)."""

    text: str
    moved: tuple[str, ...] = ()
    local_text: str | None = None
    machine_moved: tuple[tuple[str, ...], ...] = ()
    conflicts: tuple[Conflict, ...] = ()


def _check_line(lines: list[str], key: yaml.ScalarNode, value: yaml.Node) -> None:
    name = key.value
    line = key.start_mark.line
    if value.start_mark.line != line or value.end_mark.line != line:
        raise refuse(name, "its value is on more than one line, which cannot be moved by lines")
    if MARKED.search(strip_comment(lines[line])):
        raise refuse(name, "it has an anchor or an alias, which cannot be moved by lines")


def _check_block(
    lines: list[str], block_key: yaml.ScalarNode, moving: list[yaml.ScalarNode]
) -> None:
    """Refuse a block whose settings are not on its own lines: an anchor or alias on the key's
    line, or a moved key that sits on lines the block does not own."""
    line, col = block_key.start_mark.line, block_key.start_mark.column
    if MARKED.search(strip_comment(lines[line])):
        raise refuse(
            block_key.value, "the block has an anchor or an alias, which cannot be edited by lines"
        )
    last = node_end(lines, line, col)
    if any(not line < key.start_mark.line <= last for key in moving):
        raise refuse(
            block_key.value,
            "its settings are not written under it, so they cannot be moved by lines",
        )


def _check_project(
    lines: list[str], held: tuple[yaml.ScalarNode, yaml.Node], moving: list[yaml.ScalarNode]
) -> None:
    """Refuse a `project_limits` the moved lines cannot be appended to: one that already holds a
    moving setting, has an anchor or alias, is not a block of settings, or indents differently."""
    key, value = held
    names = {setting.value for setting in moving}
    if isinstance(value, yaml.MappingNode):
        for child, _ in value.value:
            if isinstance(child, yaml.ScalarNode) and child.value in names:
                raise refuse(child.value, f"it is already set in {PROJECT}")
    if MARKED.search(strip_comment(lines[key.start_mark.line])):
        raise refuse(
            PROJECT, "the block has an anchor or an alias, which cannot be edited by lines"
        )
    if isinstance(value, yaml.MappingNode):
        if value.flow_style:
            raise refuse(PROJECT, "a flow-style block cannot be edited without rewriting the line")
        columns = {child.start_mark.column for child, _ in value.value}
        if columns != {setting.start_mark.column for setting in moving} or len(columns) != 1:
            raise refuse(PROJECT, "its settings are indented differently from the ones moved")
    elif not (
        isinstance(value, yaml.ScalarNode)
        and value.tag == _NULL_TAG
        and strip_comment(lines[key.start_mark.line]).rstrip().endswith(":")
    ):
        raise refuse(PROJECT, "the block is not a mapping of settings")


def _expected(old: dict[str, Any], source: str) -> dict[str, Any]:
    block = dict(old[source] or {})
    unset = old[source] is None
    moved = {name: block.pop(name) for name in MOVED if name in block}
    renamed = {GLOBAL if key == source else key: value for key, value in old.items()}
    renamed[GLOBAL] = None if unset and not moved else block
    if moved:
        renamed[PROJECT] = {**(old.get(PROJECT) or {}), **moved}
    return renamed


def migrate(
    text: str, runtime: str = DEFAULT_RUNTIME, machine: MachineRequest | None = None
) -> Migrated:
    """Rename a root `limits` to `global_limits`, move the three scheduling settings found under
    it (or under `global_limits`) to a `project_limits` block straight after it, move
    `max_unit_lines` to `review.ceilings.full`, rename each old test-kind setting key to its new
    name, rename `limits` under each runtime and account to `usage_limits`, and move a flat `models:` block under `runtimes.<runtime>.models`, the runtime in force
    (`config.runtime_for`). Told to by `machine`, it then moves the machine settings to the local
    file's text."""
    moved = _move_limits(_move_ceiling(text))
    renamed = _rename_usage_limits(_rename_builders_key(_rename_test_kind_keys(moved.text)))
    text = _move_models(renamed, runtime)
    if machine is None:
        return Migrated(text=text, moved=moved.moved)
    machine_move = move_machine_settings(text, machine)
    return Migrated(
        text=machine_move.text,
        moved=moved.moved,
        local_text=machine_move.local_text,
        machine_moved=machine_move.moved,
        conflicts=machine_move.conflicts,
    )


def _holder(
    root: yaml.MappingNode,
) -> tuple[yaml.ScalarNode, yaml.MappingNode, yaml.ScalarNode, yaml.Node] | None:
    """The limits block (`global_limits` or the deprecated `limits`) that holds `max_unit_lines`,
    with the key's node and value; None when neither does."""
    for name in (DEPRECATED_ROOT_KEY, GLOBAL):
        held = pair(root, name)
        if held is not None and isinstance(held[1], yaml.MappingNode):
            found = pair(held[1], CEILING_KEY)
            if found is not None:
                return held[0], held[1], found[0], found[1]
    return None


def _relocate(lines: list[str], first: int, last: int, at: int, new: list[str], eol: str) -> None:
    """Delete lines `first` to `last` and insert `new` at line `at` (counted before the delete)."""
    if at > last:
        insert_lines(lines, at, new, eol)
        del lines[first : last + 1]
    else:
        del lines[first : last + 1]
        insert_lines(lines, at, new, eol)


def _empty(lines: list[str], key: yaml.ScalarNode, value: yaml.Node, name: str) -> bool:
    """Whether `key` is a bare `name:` with nothing under it; a block of another shape is
    refused."""
    if isinstance(value, yaml.MappingNode):
        return False
    bare = isinstance(value, yaml.ScalarNode) and value.tag == _NULL_TAG
    if not (bare and strip_comment(lines[key.start_mark.line]).rstrip().endswith(":")):
        raise refuse(CEILING_KEY, f"{name} is not a mapping")
    return True


def _place(lines: list[str], root: yaml.MappingNode, after: int) -> tuple[int, list[str], int]:
    """Where `full` goes: the line to insert at, the header lines to put before it, and the
    indentation of the `full` key. A new `review` block goes at line `after`; an existing one
    keeps its own indentation."""
    col = root.value[0][0].start_mark.column
    held = pair(root, REVIEW)
    if held is None:
        return after, [" " * col + f"{REVIEW}:", " " * (col + 2) + f"{CEILINGS}:"], col + 4
    key, value = held
    opened(lines, key, value, CEILING_KEY, REVIEW)
    line = key.start_mark.line
    if _empty(lines, key, value, REVIEW):
        return line + 1, [" " * (col + 2) + f"{CEILINGS}:"], col + 4
    assert isinstance(value, yaml.MappingNode)
    child = value.value[0][0].start_mark.column
    step = child - key.start_mark.column
    ceilings = pair(value, CEILINGS)
    if ceilings is None:
        at = node_end(lines, line, key.start_mark.column) + 1
        return at, [" " * child + f"{CEILINGS}:"], child + step
    ckey, cvalue = ceilings
    opened(lines, ckey, cvalue, CEILING_KEY, CEILINGS)
    cline = ckey.start_mark.line
    if _empty(lines, ckey, cvalue, CEILINGS):
        return cline + 1, [], ckey.start_mark.column + step
    assert isinstance(cvalue, yaml.MappingNode)
    at = node_end(lines, cline, ckey.start_mark.column) + 1
    return at, [], cvalue.value[0][0].start_mark.column


def _ceilings_loads(new: dict[str, Any], block: str, value: object) -> None:
    """Refuse a result whose limits and review sections do not load, or load with another
    `full` ceiling in effect than the file had."""

    def load(document: dict[str, Any]) -> WorkspaceConfig:
        limits = {k: v for k, v in (document.get(block) or {}).items() if k not in MOVED}
        sections = {block: limits, **({REVIEW: document[REVIEW]} if REVIEW in document else {})}
        return WorkspaceConfig.model_validate(sections)

    try:
        written = load(new).review.ceilings.full
    except ValueError as error:
        hint = (
            f"; raise {REVIEW}.{CEILINGS}.light and {REVIEW}.{CEILINGS}.auto to at least {value}"
            if "must not be below" in str(error)
            else ""
        )
        raise refuse(CEILING_KEY, f"the edited text would not load ({error}){hint}") from error
    if written != value:
        raise refuse(CEILING_KEY, "the edited text would put another ceiling in effect")


def _move_ceiling(text: str) -> str:
    """Move `max_unit_lines`, under `global_limits` or the deprecated `limits`, to
    `review.ceilings.full`, with its end-of-line comment and the comment lines directly above
    it; the result is checked to load with the same ceiling in effect."""
    try:
        documents = list(yaml.compose_all(text))
    except yaml.YAMLError:
        return text  # the other edits report a file that does not parse
    roots = [doc for doc in documents if isinstance(doc, yaml.MappingNode)]
    if len(documents) > 1:
        if any(_holder(root) for root in roots):
            raise refuse(
                CEILING_KEY, "the file holds several documents, and only one can be edited"
            )
        return text
    if not roots:
        return text
    root = roots[0]
    found = _holder(root)
    if found is None or (pair(root, DEPRECATED_ROOT_KEY) and pair(root, GLOBAL)):
        return text  # nothing to move, or the limits move refuses the two blocks
    block_key, block, key, value = found
    old = yaml.safe_load(text)
    lines = split_lines(text)
    eol = "\r\n" if "\r\n" in text else "\n"
    _check_block(lines, block_key, [key])
    opened(lines, block_key, block, CEILING_KEY, block_key.value)
    _check_line(lines, key, value)
    if lines[key.start_mark.line][key.start_mark.column :].split(":")[0] != CEILING_KEY:
        raise refuse(CEILING_KEY, "it is quoted or written across lines, so it is not moved")
    ceiling = old[block_key.value][CEILING_KEY]
    set_full = ((old.get(REVIEW) or {}).get(CEILINGS) or {}).get(FULL)
    if set_full is not None and set_full != ceiling:
        raise refuse(
            CEILING_KEY,
            f"{REVIEW}.{CEILINGS}.{FULL} is already set to {set_full}, not {ceiling}; "
            "keep one of them",
        )
    first, last = region(lines, key.start_mark.line, block_key.start_mark.line)
    comments = [line.strip() for line in lines[first:last]]
    if set_full is None:
        at, headers, indent = _place(
            lines, root, node_end(lines, block_key.start_mark.line, block_key.start_mark.column) + 1
        )
        rest = lines[last].rstrip("\r\n")[key.start_mark.column + len(CEILING_KEY) :]
        carried = [" " * indent + line for line in [*comments, FULL + rest]]
    else:
        # Both are set to one value: the comments go above the `full` key that stays.
        _place(lines, root, 0)
        ceilings = _block_node(root, (REVIEW, CEILINGS))
        kept = pair(ceilings, FULL) if isinstance(ceilings, yaml.MappingNode) else None
        if kept is None:
            raise refuse(CEILING_KEY, f"{REVIEW}.{CEILINGS}.{FULL} cannot be found by lines")
        tail = re.search(r"\s#.*$", lines[last].rstrip("\r\n"))
        notes = [*comments, *([tail.group().strip()] if tail else [])]
        at, headers = kept[0].start_mark.line, []
        carried = [" " * kept[0].start_mark.column + note for note in notes]
    _relocate(lines, first, last, at, [*headers, *carried], eol)
    result = joined(lines, text)
    _verify_ceiling(old, result, block_key.value, ceiling)
    return result


def _verify_ceiling(old: dict[str, Any], result: str, block: str, ceiling: object) -> None:
    try:
        new = yaml.safe_load(result)
    except yaml.YAMLError as error:
        raise refuse(CEILING_KEY, f"the edited text would not parse ({error})") from error
    left = {k: v for k, v in (old[block] or {}).items() if k != CEILING_KEY}
    review = dict(old.get(REVIEW) or {})
    review[CEILINGS] = {**(review.get(CEILINGS) or {}), FULL: ceiling}
    expected = {**old, REVIEW: review, block: left or None}
    if new != expected:
        raise refuse(
            CEILING_KEY, "the edited text would differ from the file in more than the move"
        )
    _ceilings_loads(new, block, ceiling)


def _move_limits(text: str) -> Migrated:
    try:
        documents = list(yaml.compose_all(text))
    except yaml.YAMLError as error:
        raise refuse("abk.yaml", f"the text does not parse as YAML ({error})") from error
    if len(documents) > 1:
        raise refuse("abk.yaml", "the file holds several documents, and only one can be edited")
    root = documents[0] if documents else None
    if not isinstance(root, yaml.MappingNode):
        return Migrated(text=text)

    old_pair, new_pair = pair(root, DEPRECATED_ROOT_KEY), pair(root, GLOBAL)
    if old_pair and new_pair:
        raise refuse(
            f"{DEPRECATED_ROOT_KEY} and {GLOBAL}",
            "both are set, keep one of them before the settings can be moved",
        )
    found = old_pair or new_pair
    if found is None:
        return Migrated(text=text)
    block_key, block = found
    if isinstance(block, yaml.ScalarNode):
        if block.tag != _NULL_TAG:
            raise refuse(block_key.value, "the block is not a mapping of settings")
        pairs: list[tuple[yaml.Node, yaml.Node]] = []
    elif isinstance(block, yaml.MappingNode):
        pairs = list(block.value)
    else:
        raise refuse(block_key.value, "the block is not a mapping of settings")
    if any(key.tag == MERGE_TAG for key, _ in pairs):
        raise refuse(block_key.value, "the block uses a merge key, which cannot be moved by lines")

    moving = [
        (key, value)
        for key, value in pairs
        if isinstance(key, yaml.ScalarNode) and key.value in MOVED
    ]
    renaming = block_key.value == DEPRECATED_ROOT_KEY
    if not moving and not renaming:
        return Migrated(text=text)

    held = pair(root, PROJECT)
    if moving and isinstance(block, yaml.CollectionNode) and block.flow_style:
        raise refuse(
            block_key.value, "a flow-style block cannot be edited without rewriting the line"
        )

    lines = split_lines(text)
    eol = "\r\n" if "\r\n" in text else "\n"
    block_line, col = block_key.start_mark.line, block_key.start_mark.column
    if moving:
        _check_block(lines, block_key, [key for key, _ in moving])
        if held is not None:
            _check_project(lines, held, [key for key, _ in moving])
    regions = []
    for key, value in moving:
        assert isinstance(key, yaml.ScalarNode)
        _check_line(lines, key, value)
        regions.append(region(lines, key.start_mark.line, block_line))
    carried = [line.rstrip("\r\n") for first, last in regions for line in lines[first : last + 1]]
    deleted = sum(last - first + 1 for first, last in regions)
    for first, last in reversed(regions):
        del lines[first : last + 1]

    leaving = {key.value for key, _ in moving}
    left = [
        key for key, _ in pairs if isinstance(key, yaml.ScalarNode) and key.value not in leaving
    ]
    lines[block_line] = _renamed(lines[block_line], block_key, empty=bool(moving) and not left)
    if moving and held is None:
        at = node_end(lines, block_line, col) + 1
        insert_lines(lines, at, [" " * col + f"{PROJECT}:", *carried], eol)
    elif moving and held is not None:
        # The block it is kept in shifts up by the lines taken out when it comes after them.
        held_line = held[0].start_mark.line - (
            deleted if held[0].start_mark.line > block_line else 0
        )
        at = node_end(lines, held_line, held[0].start_mark.column) + 1
        insert_lines(lines, at, carried, eol)

    result = joined(lines, text)
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
        if not strip_comment(rest).strip():
            tail = tail[:colon] + " {}" + rest
    return head + tail


def _verify(text: str, result: str, source: str) -> None:
    try:
        new = yaml.safe_load(result)
        old = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise refuse(source, f"the edited text would not parse ({error})") from error
    if new != _expected(old, source):
        raise refuse(source, "the edited text would differ from the file in more than the move")


def _block_node(root: yaml.MappingNode, path: tuple[str, ...]) -> yaml.Node | None:
    node: yaml.Node | None = root
    for name in path:
        found = pair(node, name) if isinstance(node, yaml.MappingNode) else None
        node = found[1] if found else None
    return node


def _rename_test_kind_keys(text: str) -> str:
    """`text` with each old test-kind setting key, in the limits block and in each `tests` block,
    renamed on its own line; a block that cannot be edited by lines is refused."""
    documents = list(yaml.compose_all(text))
    root = documents[0] if documents else None
    if not isinstance(root, yaml.MappingNode):
        return text
    old = yaml.safe_load(text)
    try:
        found = old_setting_blocks(old)
    except ValueError as error:
        raise refuse("abk.yaml", str(error)) from error
    if not found:
        return text

    lines = split_lines(text)
    seen: set[int] = set()
    for where, path, keys in found:
        parent = _block_node(root, path[:-1])
        held = pair(parent, path[-1]) if isinstance(parent, yaml.MappingNode) else None
        block_key, block = held if held else (None, None)
        # A block that is not written at its path is one a merge key or an alias brought in, and
        # one reached by two paths is written once for both.
        if block_key is None or not isinstance(block, yaml.MappingNode) or id(block) in seen:
            raise refuse(
                where,
                "the block comes from a merge key or an alias, which cannot be renamed by lines",
            )
        seen.add(id(block))
        opened(lines, block_key, block, where, "the block")
        for key, _ in block.value:
            if not (isinstance(key, yaml.ScalarNode) and key.value in keys):
                continue
            line, col = key.start_mark.line, key.start_mark.column
            if MARKED.search(strip_comment(lines[line])):
                raise refuse(key.value, "it has an anchor or an alias, which cannot be edited")
            if lines[line][col : col + len(key.value)] != key.value:
                raise refuse(
                    key.value, "it is quoted or written across lines, so it is not renamed"
                )
            new = new_spelling(Place.SETTING, key.value)
            lines[line] = lines[line][:col] + new + lines[line][col + len(key.value) :]
    result = "".join(lines)
    try:
        written = yaml.safe_load(result)
    except yaml.YAMLError as error:
        raise refuse("abk.yaml", f"the edited text would not parse ({error})") from error
    if written != read_new_settings(old):
        raise refuse(
            "abk.yaml", "the edited text would differ from the file in more than the rename"
        )
    return result


def _rename_builders_key(text: str) -> str:
    """`text` with `builders.per_group_commits` renamed to `builders.stubbed_tdd_commits` on its
    own line; a file that sets both, or a key that cannot be edited by lines, is refused."""
    try:
        documents = list(yaml.compose_all(text))
    except yaml.YAMLError:
        return text  # the other edits report a file that does not parse
    root = documents[0] if documents else None
    held = pair(root, "builders") if isinstance(root, yaml.MappingNode) else None
    if held is None or not isinstance(held[1], yaml.MappingNode):
        return text
    found = pair(held[1], DEPRECATED_BUILDERS_KEY)
    if found is None:
        return text
    if pair(held[1], BUILDERS_KEY) is not None:
        raise refuse(
            DEPRECATED_BUILDERS_KEY,
            f"`{DEPRECATED_BUILDERS_KEY}` and `{BUILDERS_KEY}` are both set; keep one",
        )
    lines = split_lines(text)
    opened(lines, held[0], held[1], DEPRECATED_BUILDERS_KEY, "builders")
    key = found[0]
    line, col = key.start_mark.line, key.start_mark.column
    if MARKED.search(strip_comment(lines[line])):
        raise refuse(
            DEPRECATED_BUILDERS_KEY, "it has an anchor or an alias, which cannot be edited"
        )
    if lines[line][col : col + len(DEPRECATED_BUILDERS_KEY)] != DEPRECATED_BUILDERS_KEY:
        raise refuse(
            DEPRECATED_BUILDERS_KEY, "it is quoted or written across lines, so it is not renamed"
        )
    lines[line] = (
        lines[line][:col] + BUILDERS_KEY + lines[line][col + len(DEPRECATED_BUILDERS_KEY) :]
    )
    result = "".join(lines)
    old = yaml.safe_load(text)
    builders = {
        (BUILDERS_KEY if k == DEPRECATED_BUILDERS_KEY else k): v for k, v in old["builders"].items()
    }
    try:
        written = yaml.safe_load(result)
    except yaml.YAMLError as error:
        raise refuse("abk.yaml", f"the edited text would not parse ({error})") from error
    if written != {**old, "builders": builders}:
        raise refuse(
            "abk.yaml", "the edited text would differ from the file in more than the rename"
        )
    return result


def _usage_limits_holders(
    root: yaml.MappingNode,
) -> list[tuple[str, yaml.ScalarNode, yaml.MappingNode]]:
    """Each runtime and account mapping written under `runtimes`, with its key and dotted path."""
    found = pair(root, RUNTIMES)
    if found is None or not isinstance(found[1], yaml.MappingNode):
        return []
    holders = []
    for name, runtime in found[1].value:
        if not (isinstance(name, yaml.ScalarNode) and isinstance(runtime, yaml.MappingNode)):
            continue
        holders.append((f"{RUNTIMES}.{name.value}", name, runtime))
        accounts = pair(runtime, "accounts")
        if accounts is None or not isinstance(accounts[1], yaml.MappingNode):
            continue
        for label, account in accounts[1].value:
            if isinstance(label, yaml.ScalarNode) and isinstance(account, yaml.MappingNode):
                holders.append((f"{RUNTIMES}.{name.value}.accounts.{label.value}", label, account))
    return holders


def _aliased_runtime(runtime: Any) -> Any:
    """A runtime mapping with `limits` renamed in it and in each of its accounts."""
    if not isinstance(runtime, dict):
        return runtime
    runtime = alias_usage_limits(runtime)
    accounts = runtime.get("accounts")
    if isinstance(accounts, dict):
        runtime = {
            **runtime,
            "accounts": {
                label: alias_usage_limits(account) if isinstance(account, dict) else account
                for label, account in accounts.items()
            },
        }
    return runtime


def _loaded_holds_old(document: Any, where: str) -> bool:
    """Whether the mapping at the dotted path `where` of the loaded `document` sets `limits`."""
    node = document
    for part in where.split("."):
        node = node.get(part) if isinstance(node, dict) else None
    return isinstance(node, dict) and DEPRECATED_USAGE_LIMITS in node


def _rename_usage_limits(text: str) -> str:
    """`text` with `limits` renamed to `usage_limits` under each runtime and account, on its own
    line; both spellings in one place, or a key that cannot be edited by lines, is refused."""
    try:
        documents = list(yaml.compose_all(text))
    except yaml.YAMLError:
        return text  # the other edits report a file that does not parse
    root = documents[0] if documents else None
    if not isinstance(root, yaml.MappingNode):
        return text
    lines = split_lines(text)
    before = yaml.safe_load(text)
    renamed = False
    for where, holder_key, holder in _usage_limits_holders(root):
        found = pair(holder, DEPRECATED_USAGE_LIMITS)
        if found is None:
            if any(k.tag == MERGE_TAG for k, _ in holder.value) and _loaded_holds_old(
                before, where
            ):
                opened(lines, holder_key, holder, where, "the block")
            continue
        old = f"{where}.{DEPRECATED_USAGE_LIMITS}"
        if pair(holder, USAGE_LIMITS) is not None:
            raise refuse(
                old, f"`{DEPRECATED_USAGE_LIMITS}` and `{USAGE_LIMITS}` are both set; keep one"
            )
        opened(lines, holder_key, holder, where, "the block")
        key = found[0]
        line, col = key.start_mark.line, key.start_mark.column
        if MARKED.search(strip_comment(lines[line])):
            raise refuse(old, "it has an anchor or an alias, which cannot be edited")
        if lines[line][col : col + len(DEPRECATED_USAGE_LIMITS)] != DEPRECATED_USAGE_LIMITS:
            raise refuse(old, "it is quoted or written across lines, so it is not renamed")
        lines[line] = (
            lines[line][:col] + USAGE_LIMITS + lines[line][col + len(DEPRECATED_USAGE_LIMITS) :]
        )
        renamed = True
    if not renamed:
        return text
    result = joined(lines, text)
    expected = {
        **before,
        RUNTIMES: {name: _aliased_runtime(entry) for name, entry in before[RUNTIMES].items()},
    }
    try:
        written = yaml.safe_load(result)
    except yaml.YAMLError as error:
        raise refuse("abk.yaml", f"the edited text would not parse ({error})") from error
    if written != expected:
        raise refuse(
            "abk.yaml", "the edited text would differ from the file in more than the rename"
        )
    return result


def _move_models(text: str, name: str) -> str:
    """Move a root `models:` block, its lines and comments as they are, under
    `runtimes.<name>.models` of the runtime `name`, the one in force."""
    try:
        documents = list(yaml.compose_all(text))
    except yaml.YAMLError as error:
        raise refuse("abk.yaml", f"the text does not parse as YAML ({error})") from error
    root = documents[0] if documents else None
    found = pair(root, MODELS) if isinstance(root, yaml.MappingNode) else None
    if not isinstance(root, yaml.MappingNode) or found is None:
        return text
    old = yaml.safe_load(text)
    target = f"{RUNTIMES}.{name}.{MODELS}"
    block_key, block = found
    if isinstance(block, yaml.ScalarNode) and block.tag == _NULL_TAG:
        return text
    if not isinstance(block, yaml.MappingNode):
        raise refuse(MODELS, "the block is not a mapping of roles")
    if not block.value:
        return text  # `models: {}` names no role, so there is nothing to move
    lines = split_lines(text)
    opened(lines, block_key, block, MODELS, "the block")
    eol = "\r\n" if "\r\n" in text else "\n"
    first, col = block_key.start_mark.line, block_key.start_mark.column
    last = node_end(lines, first, col)
    child = block.value[0][0].start_mark.column
    body = lines[first + 1 : last + 1]
    header = lines[first].strip()

    def place(indent: int, parents: list[str]) -> list[str]:
        """The headers down to `models:` at `indent`, then the body under it."""
        return [*parents, " " * indent + header, *shifted(body, indent + 2 - child)]

    held = pair(root, RUNTIMES)
    if held is None:
        new = place(col + 4, [" " * col + f"{RUNTIMES}:", " " * (col + 2) + f"{name}:"])
        at = first
    else:
        key, entries = held
        key_line, key_col = key.start_mark.line, key.start_mark.column
        empty = isinstance(entries, yaml.MappingNode) and not entries.value
        if not isinstance(entries, yaml.MappingNode) or (entries.flow_style and not empty):
            raise refuse(RUNTIMES, "the block cannot be edited by lines")
        if empty:
            lines[key_line] = lines[key_line].replace("{}", "").rstrip() + eol
            indent = key_col + 2
        else:
            indent = entries.value[0][0].start_mark.column
        entry = pair(entries, name)
        if entry is None:
            at = node_end(lines, key_line, key_col) + 1
            new = place(indent + 2, [" " * indent + f"{name}:"])
        else:
            entry_key, value = entry
            if not isinstance(value, yaml.MappingNode) or value.flow_style or not value.value:
                raise refuse(target, "the entry cannot be edited by lines")
            if pair(value, MODELS):
                raise refuse(target, "it is already set there; merge the flat block into it")
            at = node_end(lines, entry_key.start_mark.line, entry_key.start_mark.column) + 1
            new = place(value.value[0][0].start_mark.column, [])
    _relocate(lines, first, last, at, new, eol)

    result = joined(lines, text)
    expected = {key: value for key, value in old.items() if key != MODELS}
    runtimes = {key: dict(value or {}) for key, value in (old.get(RUNTIMES) or {}).items()}
    runtimes.setdefault(name, {})[MODELS] = old[MODELS]
    expected[RUNTIMES] = runtimes
    try:
        written = yaml.safe_load(result)
    except yaml.YAMLError as error:
        raise refuse(MODELS, f"the edited text would not parse ({error})") from error
    if written != expected:
        raise refuse(MODELS, "the edited text would differ from the file in more than the move")
    return result
