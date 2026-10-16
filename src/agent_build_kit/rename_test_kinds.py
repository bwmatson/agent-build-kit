"""Rewrites the old spellings of the test kinds to the new ones over the paths it is given.

Run as `python -m agent_build_kit.rename_test_kinds --paths <path>...`. It rewrites by token,
so a word that merely contains an old spelling is unaffected, and keeps the case style of
each spelling it finds.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from collections.abc import Sequence
from pathlib import Path

from agent_build_kit.compat_names import KIND_FORMS
from agent_build_kit.pipeline.shell import git

# Files that hold the old spellings on purpose: the table of them, this tool, and their tests.
_EXEMPT_NAMES = ("compat_names.py", "test_compat_names.py", "rename_test_kinds.py")
_EXEMPT_PREFIX = "test_rename_test_kinds"

# Ends each line the tool leaves behind for old importers; such lines are never rewritten.
SHIM_MARKER = "# abk-shim"

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


def _shim_names(text: str) -> list[str]:
    """The top-level classes, functions and variables of module source `text` whose name
    carries an old spelling."""
    names: list[str] = []
    for node in ast.parse(text).body:
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            names.append(node.name)
        elif isinstance(node, ast.Assign):
            names.extend(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.append(node.target.id)
    return [name for name in names if _rewrite(name) != name]


def _aliases(text: str) -> str:
    return "".join(
        f"{name} = {_rewrite(name)}  {SHIM_MARKER}\n" for name in dict.fromkeys(_shim_names(text))
    )


def _rewrite_text(text: str, *, prose: bool) -> str:
    """Rewrite `text` line by line, leaving the lines that mark a shim as they are."""
    lines = text.splitlines(keepends=True)
    return "".join(line if SHIM_MARKER in line else _rewrite(line, prose=prose) for line in lines)


def _is_shim_module(text: str) -> bool:
    lines = [line for line in text.splitlines() if line.strip()]
    return bool(lines) and all(SHIM_MARKER in line for line in lines)


def _decode(raw: bytes) -> str | None:
    try:
        return raw.decode()
    except UnicodeDecodeError:
        return None


def _remove_shims(root: Path, files: Sequence[Path], *, dry_run: bool) -> list[Path]:
    changed: list[Path] = []
    for file in files:
        text = _decode(file.read_bytes())
        if text is None or SHIM_MARKER not in text:
            continue
        if not dry_run:
            if _is_shim_module(text):
                git(root, "rm", "-q", "-f", str(file))
            else:
                kept = [line for line in text.splitlines(keepends=True) if SHIM_MARKER not in line]
                file.write_text("".join(kept))
        changed.append(file.relative_to(root))
    return changed


def rename_paths(
    root: Path,
    paths: Sequence[Path],
    *,
    shims: bool = False,
    remove_shims: bool = False,
    dry_run: bool = False,
) -> list[Path]:
    """Rewrite the old spellings in the tracked files under `paths` (files or folders under
    `root`) and rename the ones whose name carries one; returns the files changed, relative to
    `root`. With `shims`, a renamed Python module is left behind as a one-line re-export and each
    renamed top-level name stays bound under its old name; `remove_shims` deletes those instead
    of renaming anything. `dry_run` only lists what would change. Raises `PathOutsideRoot`,
    changing nothing, when a path is outside `root`."""
    root = root.resolve()
    resolved = [Path(path).resolve() for path in paths]
    for path in resolved:
        if not path.is_relative_to(root):
            raise PathOutsideRoot(f"{path} is outside {root}")
    files = _files(root, resolved)
    if remove_shims:
        return _remove_shims(root, files, dry_run=dry_run)
    changed: list[Path] = []
    for file in files:
        raw = file.read_bytes()
        text = _decode(raw)
        if text is None:
            new_text = None
            new_raw = raw
        elif _is_shim_module(text):
            continue
        else:
            new_text = _rewrite_text(text, prose=file.suffix in _PROSE_SUFFIXES)
            if (
                shims
                and file.suffix == ".py"
                and (new_text != text or file.name != _rewrite(file.name))
            ):
                new_text += _aliases(text)
            new_raw = new_text.encode()
        new_name = _rewrite(file.name)
        if new_raw == raw and new_name == file.name:
            continue
        target = file.with_name(new_name)
        if not dry_run:
            if new_raw != raw:
                file.write_bytes(new_raw)
            if new_name != file.name:
                git(root, "mv", str(file), str(target))
                if shims and file.suffix == ".py":
                    file.write_text(f"from .{target.stem} import *  {SHIM_MARKER}\n")
                    git(root, "add", str(file))
        changed.append(target.relative_to(root))
    return changed


def main(argv: Sequence[str] | None = None, *, root: Path | None = None) -> int:
    """The command line: `--paths` names what to rewrite; each changed file is printed, one per
    line. `root` is the framework repository unless given. Returns 2 for a refused path."""
    parser = argparse.ArgumentParser(prog="rename_test_kinds", description=__doc__)
    parser.add_argument("--paths", nargs="+", type=Path, required=True)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--shims", action="store_true")
    parser.add_argument("--remove-shims", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    base = args.root or root or Path(__file__).resolve().parents[2]
    try:
        changed = rename_paths(
            base,
            args.paths,
            shims=args.shims,
            remove_shims=args.remove_shims,
            dry_run=args.dry_run,
        )
    except PathOutsideRoot as error:
        print(error, file=sys.stderr)
        return 2
    for path in changed:
        print(path.as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
