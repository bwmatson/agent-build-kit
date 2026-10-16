"""Rewrites the old spellings of the test kinds to the new ones over the paths it is given.

Run as `python -m agent_build_kit.rename_test_kinds --paths <path>...`. It rewrites by token,
so a word that merely contains an old spelling is unaffected, and keeps the case style of
each spelling it finds.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from pathlib import Path

from agent_build_kit.compat_names import KIND_FORMS
from agent_build_kit.pipeline.shell import git

# Files that hold the old spellings on purpose: the table of them, this tool, and their tests.
_EXEMPT_NAMES = ("compat_names.py", "test_compat_names.py", "rename_test_kinds.py")
_EXEMPT_PREFIX = "test_rename_test_kinds"

_OLD = re.compile(r"(tier|Tier|TIER)( ?)([12])")

# Prose files hold a bare old spelling as a word; elsewhere a bare one is an identifier.
_PROSE_SUFFIXES = (".md", ".rst", ".txt")
_OPENERS = ("[", '"', "'", "`", "/")
_CLOSERS = ("]", '"', "'", "`")


class PathOutsideRoot(ValueError):
    """A path given to the tool lies outside the root it works under."""


def _camel(stem: str) -> str:
    return "".join(part.capitalize() for part in stem.split("_"))


def _replace(found: re.Match[str], *, prose: bool) -> str:
    text, word, space, number = found.string, found[1], found[2], found[3]
    before = text[found.start() - 1 : found.start()]
    after = text[found.end() : found.end() + 1]
    if after.isdigit():
        return found[0]
    if word == "Tier":
        if after.islower():
            return found[0]
    elif before.isalnum() or after.isalpha():
        return found[0]
    forms = KIND_FORMS[f"tier{number}"]
    if space:
        new = forms.tag
    elif before in ("_", ".") or after in ("_", "."):
        new = forms.stem
    elif before == "-" or after == "-":
        new = forms.file_stem
    elif word == "tier":
        delimited = before in _OPENERS or after in _CLOSERS
        return forms.tag if prose or delimited else forms.stem
    elif word == "Tier":
        return _camel(forms.stem)
    else:
        return forms.stem.upper()
    if word == "TIER":
        return new.upper()
    return new[0].upper() + new[1:] if word == "Tier" else new


def _rewrite(text: str, *, prose: bool = False) -> str:
    return _OLD.sub(lambda found: _replace(found, prose=prose), text)


def _exempt(path: Path) -> bool:
    return path.name in _EXEMPT_NAMES or path.name.startswith(_EXEMPT_PREFIX)


def _files(root: Path, paths: Sequence[Path]) -> list[Path]:
    """The files git tracks under `paths`, so an ignored or untracked file is never touched."""
    listed = git(root, "ls-files", "-z", "--", *map(str, paths)).stdout.split("\0")
    files = (root / name for name in listed if name)
    return sorted(file for file in files if not _exempt(file))


def rename_paths(root: Path, paths: Sequence[Path]) -> list[Path]:
    """Rewrite the old spellings in the tracked files under `paths` (files or folders under
    `root`) and rename the ones whose name carries one; returns the files changed, relative to
    `root`. Raises `PathOutsideRoot`, changing nothing, when a path is outside `root`."""
    root = root.resolve()
    resolved = [Path(path).resolve() for path in paths]
    for path in resolved:
        if not path.is_relative_to(root):
            raise PathOutsideRoot(f"{path} is outside {root}")
    changed: list[Path] = []
    for file in _files(root, resolved):
        raw = file.read_bytes()
        try:
            text = raw.decode()
        except UnicodeDecodeError:
            new_raw = raw
        else:
            new_raw = _rewrite(text, prose=file.suffix in _PROSE_SUFFIXES).encode()
        new_name = _rewrite(file.name)
        if new_raw == raw and new_name == file.name:
            continue
        if new_raw != raw:
            file.write_bytes(new_raw)
        target = file
        if new_name != file.name:
            target = file.with_name(new_name)
            git(root, "mv", str(file), str(target))
        changed.append(target.relative_to(root))
    return changed


def main(argv: Sequence[str] | None = None, *, root: Path | None = None) -> int:
    """The command line: `--paths` names what to rewrite; each changed file is printed, one per
    line. `root` is the framework repository unless given. Returns 2 for a refused path."""
    parser = argparse.ArgumentParser(prog="rename_test_kinds", description=__doc__)
    parser.add_argument("--paths", nargs="+", type=Path, required=True)
    args = parser.parse_args(argv)
    base = root if root is not None else Path(__file__).resolve().parents[2]
    try:
        changed = rename_paths(base, args.paths)
    except PathOutsideRoot as error:
        print(error, file=sys.stderr)
        return 2
    for path in changed:
        print(path.as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
