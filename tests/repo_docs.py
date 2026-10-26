"""Test support: the Markdown files of the repository, walked in one place."""

from collections.abc import Collection
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIPPED_DIRS = {"node_modules", ".venv", "__pycache__"}
# The planning store and the run reports describe past states: the document rules do not read them.
# The leak test (`tests/installation_leaks.py`) still scans them.
PLANNING_STORE = {"openspec", "runs"}


def repo_markdown(exclude: Collection[Path] = ()) -> list[Path]:
    """Every Markdown file of the repository but the hidden folders (which hold the skills'
    mirror), the vendored folders, the planning store and the excluded files and folders."""
    return sorted(
        path
        for path in ROOT.rglob("*.md")
        if not any(
            part.startswith(".") or part in SKIPPED_DIRS for part in path.relative_to(ROOT).parts
        )
        and path.relative_to(ROOT).parts[0] not in PLANNING_STORE
        and path not in exclude
        and not any(folder in path.parents for folder in exclude)
    )
