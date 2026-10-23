"""Writing what `abk config --migrate` moves: abk.yaml and abk.local.yaml together or not at all,
git told to ignore the local files, and the notices the person sees before and after the write
(spec: config-migration)."""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import Any

import yaml

from agent_build_kit.config import merge_local, overlay_path
from agent_build_kit.config_migrate import ConfigMigrateError
from agent_build_kit.pipeline.file_lock import append_missing_lines
from agent_build_kit.pipeline.shell import git, is_ignored, is_tracked
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import RUNNING
from agent_build_kit.runtimes.policy_apply import (
    backup_once,
    install_staged,
    replace_text,
    stage_text,
)

IGNORED_LOCAL_FILES = ("abk.local.yaml", "scrub.local")
_SHOWN_IDS = 5
_WARNING = (
    "A write to abk.yaml or abk.local.yaml fails a build or track run in progress, so run this"
)


def in_repository(directory: Path) -> bool:
    return git(directory, "rev-parse", "--is-inside-work-tree", check=False).returncode == 0


def _diff(path: Path, before: str, after: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=str(path),
            tofile=str(path),
        )
    )


def _missing_ignores(directory: Path) -> list[str]:
    """The local-file names git does not ignore yet; refuses a tracked abk.local.yaml."""
    if is_tracked(directory, "abk.local.yaml"):
        raise ConfigMigrateError(
            f"{directory / 'abk.local.yaml'} is tracked by git, which would commit machine "
            "settings; run `git rm --cached abk.local.yaml` and migrate again"
        )
    return [name for name in IGNORED_LOCAL_FILES if not is_ignored(directory, name)]


def ignore_diff(directory: Path) -> str:
    """The diff of the `.gitignore` in `directory` as the writer will change it, empty when git
    already ignores both local files; writes nothing. Refuses a tracked abk.local.yaml."""
    missing = _missing_ignores(directory)
    if not missing:
        return ""
    path = directory / ".gitignore"
    try:
        before = path.read_text() if path.exists() else ""
    except OSError as error:
        raise ConfigMigrateError(f"{path}: {error}") from error
    separator = "" if not before or before.endswith("\n") else "\n"
    after = before + separator + "".join(f"{name}\n" for name in missing)
    return _diff(path, before, after)


def _ignore_local_files(directory: Path, show: bool) -> None:
    """Refuse a tracked abk.local.yaml; append the lines git lacks to `.gitignore`, showing the
    change when `show`."""
    missing = _missing_ignores(directory)
    if not missing:
        return
    path = directory / ".gitignore"
    try:
        before = path.read_text() if path.exists() else ""
        append_missing_lines(path, missing)
        after = path.read_text()
    except OSError as error:
        raise ConfigMigrateError(f"{path}: {error}") from error
    if show:
        print(_diff(path, before, after), end="")


def _staged(path: Path, text: str, mode: int) -> Path:
    """`text` in a temporary beside `path`, read back and compared."""
    staged = stage_text(path, text, mode)
    try:
        if staged.read_bytes().decode() != text:
            raise OSError(f"{staged} does not read back as written")
    except BaseException:
        staged.unlink(missing_ok=True)
        raise
    return staged


def write_both(
    base: Path, base_text: str, local_text: str, *, show_ignore_diff: bool = True
) -> None:
    """Write `base_text` over the abk.yaml at `base` and `local_text` over the abk.local.yaml
    beside it, local first, both or neither; raises `ConfigMigrateError` naming the file that
    failed or the refusal (a tracked abk.local.yaml). In a git repository it first appends the
    missing `.gitignore` lines for `abk.local.yaml` and `scrub.local` and prints their diff;
    after the backups are made it prints their paths. A caller that has shown `ignore_diff`
    already passes `show_ignore_diff=False`."""
    local = overlay_path(base)
    if in_repository(base.parent):
        _ignore_local_files(base.parent, show_ignore_diff)
    failing = base
    staged: list[Path] = []
    replaced = False
    try:
        local_before = local.read_bytes() if local.exists() else None
        mode = base.stat().st_mode
        local_mode = local.stat().st_mode if local_before is not None else mode
    except OSError as error:
        raise ConfigMigrateError(f"{base}: {error}") from error
    try:
        for path in (base, local):
            failing = path
            if path.exists() and (made := backup_once(path)):
                print(f"backed up the original to {made}")
        failing = local
        staged.append(_staged(local, local_text, local_mode))
        failing = base
        staged.append(_staged(base, base_text, mode))
        failing = local
        install_staged(staged[0], local)
        replaced = True
        failing = base
        install_staged(staged[1], base)
    except OSError as error:
        for path in staged:
            path.unlink(missing_ok=True)
        if replaced:
            _undo(local, local_before, local_mode)
        raise ConfigMigrateError(f"{failing}: {error}") from error


def _undo(local: Path, original: bytes | None, mode: int) -> None:
    """Put the local file back as it was before this run, or remove it when this run made it. A
    restore that fails leaves the setting in both files, which merges to the same configuration."""
    if original is None:
        local.unlink(missing_ok=True)
        return
    try:
        replace_text(local, original.decode(), mode)
    except (OSError, UnicodeDecodeError):
        pass


def uncommitted_hint(base: Path) -> str | None:
    """The hint that the abk.yaml at `base` has changes git has not committed and that the
    migration does not commit, or None when it has none or is not in a git repository."""
    if not in_repository(base.parent):
        return None
    status = git(base.parent, "status", "--porcelain", "--", base.name, check=False)
    if status.returncode or not status.stdout.strip():
        return None
    return (
        f"{base.name} has changes git has not committed; this migration does not commit, "
        f"so review `git diff {base.name}` and commit it yourself"
    )


def _raw(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(path.read_text()) if path.exists() else None
    return document if isinstance(document, dict) else {}


def running_units_notice(base: Path) -> str | None:
    """The notice naming the units in state `running` of the unit store the abk.yaml at `base`
    (with its abk.local.yaml) points to, read without loading the configuration; None when there
    is no such unit or the store cannot be read."""
    try:
        merged = merge_local(_raw(base), _raw(overlay_path(base)))
        planning = merged.get("planning")
        state_dir = planning.get("state_dir") if isinstance(planning, dict) else None
        directory = base.parent / Path(str(state_dir or "runs")).expanduser()
        units = UnitStore(directory / "units.json").all()
    except (OSError, ValueError, yaml.YAMLError):
        return None
    ids = [unit.id for unit in units if unit.state == RUNNING]
    if not ids:
        return None
    named = ", ".join(ids[:_SHOWN_IDS])
    if len(ids) > _SHOWN_IDS:
        named += f", and {len(ids) - _SHOWN_IDS} more"
    if len(ids) == 1:
        return (
            f"abk: 1 unit is running ({named}). {_WARNING} between ticks or when it has finished."
        )
    return (
        f"abk: {len(ids)} units are running ({named}). {_WARNING} between ticks or when they "
        "have finished."
    )
