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

from agent_build_kit.pipeline.shell import git

# Files that hold the old spellings on purpose: the table of them, this tool, and their tests.
_EXEMPT_NAMES = ("compat_names.py", "test_compat_names.py", "rename_test_kinds.py")
_EXEMPT_PREFIX = "test_rename_test_kinds"

# (identifier stem, file-name stem, prose form, CamelCase form) of each kind, by its number.
_FORMS = {
    "1": ("unit_test", "unit-test", "unit-test", "UnitTest"),
    "2": ("e2e", "e2e", "e2e-test", "E2e"),
}

_OLD = re.compile(r"(tier|Tier|TIER)( ?)([12])")


class PathOutsideRoot(ValueError):
    """A path given to the tool lies outside the root it works under."""


def _replace(found: re.Match[str]) -> str:
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
    stem, file_stem, prose, camel = _FORMS[number]
    if space:
        new = prose
    elif before in ("_", ".") or after in ("_", "."):
        new = stem
    elif before == "-" or after == "-":
        new = file_stem
    else:
        new = camel if word == "Tier" else prose
        return new.upper().replace("-", "_") if word == "TIER" else new
    if word == "TIER":
        return new.upper()
    return new[0].upper() + new[1:] if word == "Tier" else new


def _rewrite(text: str) -> str:
    return _OLD.sub(_replace, text)


def _exempt(path: Path) -> bool:
    return path.name in _EXEMPT_NAMES or path.name.startswith(_EXEMPT_PREFIX)


def _files(paths: Sequence[Path]) -> list[Path]:
    found: set[Path] = set()
    for path in paths:
        for file in [path, *path.rglob("*")] if path.is_dir() else [path]:
            if file.is_file() and ".git" not in file.parts and not _exempt(file):
                found.add(file)
    return sorted(found)


def rename_paths(root: Path, paths: Sequence[Path]) -> list[Path]:
    """Rewrite the old spellings in `paths` (files or folders under `root`) and rename the
    files that carry one; returns the files changed, relative to `root`. Raises
    `PathOutsideRoot`, changing nothing, when a path is outside `root`."""
    root = root.resolve()
    resolved = [Path(path).resolve() for path in paths]
    for path in resolved:
        if not path.is_relative_to(root):
            raise PathOutsideRoot(f"{path} is outside {root}")
    changed: list[Path] = []
    for file in _files(resolved):
        try:
            text = file.read_text()
        except UnicodeDecodeError:
            text = None
        new_text = None if text is None else _rewrite(text)
        new_name = _rewrite(file.name)
        if new_text is None or new_text == text:
            if new_name == file.name:
                continue
        else:
            file.write_text(new_text)
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
