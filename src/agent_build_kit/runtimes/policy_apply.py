"""Merge the recommended policy into a known agent's configuration, over its descriptor.

Add only: the operator's entries stay and come first, comments and every other key are kept,
the original is copied once to `<file>.abk-backup`, and the write goes through a temporary
file beside the target. The engine takes the resolved home as an argument; `resolve_home` is
the one place a variable is looked at.
"""

from __future__ import annotations

import difflib
import os
import shutil
import tempfile
from collections.abc import Callable, Iterable
from enum import StrEnum
from io import StringIO
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.error import YAMLError

from agent_build_kit.model import Frozen
from agent_build_kit.runtimes.known_agents import ApplyFormat, ApplyPolicy
from agent_build_kit.runtimes.recommended_policy import patterns
from agent_build_kit.settings import named_value

BACKUP_SUFFIX = ".abk-backup"


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
# and, when `toolset` is given, sets the list at its path; it raises `ApplyRefused` naming `label`.
Writer = Callable[[str, ApplyPolicy, list[str], tuple[str, ...] | None, str], Merged]


def _dotted(path: tuple[str, ...]) -> str:
    return ".".join(path)


def _yaml(descriptor: ApplyPolicy) -> YAML:
    yaml = YAML(typ="rt")
    yaml.version = (1, 1) if descriptor.yaml_version == "1.1" else (1, 2)
    yaml.preserve_quotes = True
    yaml.width = 1_000_000
    yaml.allow_unicode = True
    yaml.default_flow_style = False
    yaml.indent(mapping=2, sequence=4, offset=2)
    return yaml


def _list_at(root: CommentedMap, path: tuple[str, ...], label: str) -> CommentedSeq:
    """The list at `path`, creating missing sections and the list; a string is its first item."""
    node = root
    for depth, key in enumerate(path[:-1], start=1):
        if key not in node:
            node[key] = CommentedMap()
        node = node[key]
        if not isinstance(node, CommentedMap):
            raise ApplyRefused(
                f"{label}: {_dotted(path[:depth])} is not a mapping, "
                f"so {_dotted(path)} cannot be set"
            )
    last = path[-1]
    value = node.get(last)
    if value is None:
        value = CommentedSeq()
        node[last] = value
    elif isinstance(value, str):
        value = CommentedSeq([value])
        node[last] = value
    elif not isinstance(value, CommentedSeq):
        raise ApplyRefused(f"{label}: {_dotted(path)} is not a list")
    return value


def _merge_yaml(
    text: str,
    descriptor: ApplyPolicy,
    wanted: list[str],
    toolset: tuple[str, ...] | None,
    label: str,
) -> Merged:
    yaml = _yaml(descriptor)
    try:
        root = yaml.load(text)
    except YAMLError as exc:
        raise ApplyRefused(f"{label} does not parse as YAML: {exc}") from exc
    if root is None:
        root = CommentedMap()
    if not isinstance(root, CommentedMap):
        raise ApplyRefused(f"{label}: the top level is not a mapping")
    deny = _list_at(root, descriptor.deny_path, label)
    added = tuple(p for p in dict.fromkeys(wanted) if p not in deny)
    deny.extend(added)
    change = None
    if toolset is not None and descriptor.toolset is not None:
        current = _list_at(root, descriptor.toolset.path, label)
        before = tuple(str(item) for item in current)
        if before != toolset:
            current[:] = list(toolset)
            change = (before, toolset)
    if not added and change is None:
        return Merged(text=text, added=(), toolset_change=None)
    out = StringIO()
    yaml.dump(root, out)
    return Merged(text=out.getvalue(), added=added, toolset_change=change)


# A writer per format; the table's structural test fails a row naming one without.
WRITERS: dict[ApplyFormat, Writer] = {ApplyFormat.YAML: _merge_yaml}


def resolve_home(descriptor: ApplyPolicy, env_file: Path | None = None) -> Path:
    """The agent's home: the descriptor's variable when set, else its default under the home."""
    named = named_value(descriptor.home_env, env_file)
    return Path(named) if named else Path.home() / descriptor.home_default


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
    if not path.is_file():
        return ApplyResult(
            path=path,
            status=Status.ABSENT,
            message=(
                f"no configuration at {path}; the agent is not installed or its home is "
                f"elsewhere (set {descriptor.home_env})"
            ),
        )
    before = path.read_text()
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
    backup = path.with_name(path.name + BACKUP_SUFFIX)
    made = None
    if not backup.exists():
        shutil.copy2(path, backup)
        made = backup
    _replace(path, merged.text)
    return result.model_copy(update={"backup": made})


def _replace(path: Path, text: str) -> None:
    """Write `text` over `path` through a temporary beside it, keeping the file's mode."""
    mode = path.stat().st_mode
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(text)
        os.chmod(name, mode & 0o7777)
        os.replace(name, path)
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise
