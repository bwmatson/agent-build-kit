"""What the tests of the migration's writer share: a tracked abk.yaml that holds a repo path, the
local file that takes it, and the ways a write can be made to fail."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from agent_build_kit.config import merge_local
from agent_build_kit.runtimes.policy_apply import BACKUP_SUFFIX

BASE_OLD = "version: 1\nrepos:\n  app:\n    slug: example/app\n    path: ../app\n"
BASE_NEW = "version: 1\nrepos:\n  app:\n    slug: example/app\n"
LOCAL_OLD = "repos:\n  app:\n    account: work\n"
LOCAL_NEW = "repos:\n  app:\n    account: work\n    path: ../app\n"


def files(directory: Path, *, local: str | None = LOCAL_OLD) -> tuple[Path, Path]:
    """The abk.yaml, and the abk.local.yaml beside it (not written when `local` is None)."""
    directory.mkdir(parents=True, exist_ok=True)
    base = directory / "abk.yaml"
    base.write_text(BASE_OLD)
    overlay = directory / "abk.local.yaml"
    if local is not None:
        overlay.write_text(local)
    return base, overlay


def merged(base: Path, overlay: Path) -> dict:
    """The configuration the two files make together."""
    document = yaml.safe_load(base.read_text()) or {}
    local = yaml.safe_load(overlay.read_text()) if overlay.exists() else {}
    return merge_local(document, local or {})


def temporaries(directory: Path) -> list[str]:
    """Every file in the directory that is neither a config file, a backup nor `.gitignore`."""
    return sorted(
        entry.name
        for entry in directory.iterdir()
        if entry.name not in ("abk.yaml", "abk.local.yaml", ".gitignore", ".git")
        and not entry.name.endswith(BACKUP_SUFFIX)
    )


def fail_nth(
    monkeypatch: pytest.MonkeyPatch, name: str, first: int, last: int | None = None
) -> list[tuple[str, str]]:
    """Make the calls of `os.<name>` from the `first` (1-based) through the `last` (every later
    one when None) raise, and return the (source, target) of every call made."""
    real = getattr(os, name)
    calls: list[tuple[str, str]] = []

    def wrapper(*args: object, **kwargs: object) -> object:
        calls.append((str(args[0]), str(args[1]) if len(args) > 1 else ""))
        if len(calls) >= first and (last is None or len(calls) <= last):
            raise OSError(28, "No space left on device")
        return real(*args, **kwargs)

    monkeypatch.setattr(os, name, wrapper)
    return calls
