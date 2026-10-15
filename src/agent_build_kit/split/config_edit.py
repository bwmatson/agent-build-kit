"""Adding a repo's entry to the destination's abk.yaml by a checked text splice."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.init.scaffold import (
    ScaffoldError,
    block_end,
    checked,
    child_indent,
    indent_of,
    key_at,
    key_line,
    read_lines,
    repo_block,
)
from agent_build_kit.model import Frozen
from agent_build_kit.runtimes.policy_apply import backup_and_replace

__all__ = ["ConfigEditError", "RepoEntry", "add_repo_entry"]


class ConfigEditError(ValueError):
    """The file's layout cannot be followed, or the result is not the old document plus the
    entry; nothing was written."""


class RepoEntry(Frozen):
    """What adding the entry did (or, with `write=False`, would do)."""

    already_declared: bool = False
    written: bool = False
    # `consumes:` entries of the block that name a repo the destination does not declare.
    missing_consumes: tuple[str, ...] = ()


def _reindented(block: list[str], source_indent: int, source_step: int, indent: int, step: int):
    out = []
    for line in block:
        if not line.strip():
            out.append(line)
            continue
        relative = indent_of(line) - source_indent
        width = indent + relative // source_step * step + relative % source_step
        out.append(" " * width + line.lstrip())
    return out


def add_repo_entry(source: Path, destination: Path, repo: str, *, write: bool = True) -> RepoEntry:
    """Splice `repos.<repo>` of the `source` abk.yaml into the `destination` one, after the
    last repo block, as text. A repo the destination declares is left. The original is copied
    once to `<file>.abk-backup`; a layout that cannot be followed, or a result that does not
    parse to the old document plus the block, raises `ConfigEditError` and writes nothing."""
    source_raw, source_lines = read_lines(source)
    raw, lines = read_lines(destination)
    entry = (source_raw.get("repos") or {}).get(repo)
    declared = raw.get("repos") or {}
    if repo in declared:
        return RepoEntry(already_declared=True)
    missing = tuple(
        name
        for name in (entry or {}).get("consumes") or []
        if name not in declared and name != repo
    )

    found = repo_block(source_lines, repo)
    if not isinstance(entry, dict) or found is None:
        raise ConfigEditError(
            f"{source}: cannot find a block entry for repo {repo!r} under `repos:`"
        )
    start, end, source_indent = found
    repos = key_line(lines, "repos", top=True)
    if repos is None or not isinstance(raw.get("repos"), dict):
        raise ConfigEditError(f"{destination}: cannot find a block `repos:` to add {repo!r} to")

    indent = len(child_indent(lines, repos, 0))
    last = block_end(lines, repos, lambda line: indent_of(line) > 0)
    firsts = (key_at(lines, name, start=repos + 1, stop=last, indent=indent) for name in declared)
    first = next((at for at in firsts if at is not None), None)
    step = len(child_indent(lines, first, indent)) - indent if first is not None else 2
    source_step = len(child_indent(source_lines, start, source_indent)) - source_indent
    lines[last:last] = _reindented(
        source_lines[start:end], source_indent, source_step, indent, step
    )
    updated = "".join(lines)

    try:
        checked(destination, updated, {**raw, "repos": {**declared, repo: entry}})
    except ScaffoldError as error:
        raise ConfigEditError(f"{error} (adding {repo!r})") from error
    if write:
        backup_and_replace(destination, updated)
    return RepoEntry(written=write, missing_consumes=missing)
