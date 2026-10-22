"""A throwaway git work tree standing in for the checkout the kit's code is imported from."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline import loaded_code
from tests.factories import commit, init_repo


def kit_at(path: Path, patch: pytest.MonkeyPatch, *, commits: bool = True) -> str | None:
    """Make `path`, a git work tree, the checkout the package was imported from, with a source
    folder below it as the package's own; the head it holds (None with `commits=False`)."""
    init_repo(path)
    package = path / "src" / "pkg"
    package.mkdir(parents=True)
    patch.setattr(loaded_code, "PACKAGE_DIR", package)
    return commit(path, "kit.txt") if commits else None
