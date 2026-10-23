"""Writing what `abk config --migrate` moves: abk.yaml and abk.local.yaml together or not at all,
git told to ignore the local files, and the notices the person sees before and after the write
(spec: config-migration)."""

from __future__ import annotations

from pathlib import Path


def write_both(base: Path, base_text: str, local_text: str) -> None:
    """Write `base_text` over the abk.yaml at `base` and `local_text` over the abk.local.yaml
    beside it, local first, both or neither; raises `ConfigMigrateError` naming the file that
    failed or the refusal (a tracked abk.local.yaml). In a git repository it first appends the
    missing `.gitignore` lines for `abk.local.yaml` and `scrub.local` and prints their diff;
    after the backups are made it prints their paths."""
    raise NotImplementedError


def uncommitted_hint(base: Path) -> str | None:
    """The hint that the abk.yaml at `base` has changes git has not committed and that the
    migration does not commit, or None when it has none or is not in a git repository."""
    raise NotImplementedError


def running_units_notice(base: Path) -> str | None:
    """The notice naming the units in state `running` of the unit store the abk.yaml at `base`
    (with its abk.local.yaml) points to, read without loading the configuration; None when there
    is no such unit or the store cannot be read."""
    raise NotImplementedError
