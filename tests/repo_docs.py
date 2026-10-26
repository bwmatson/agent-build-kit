"""Test support: the Markdown files of the repository, walked in one place."""

from collections.abc import Collection
from pathlib import Path

from tests.tracked_files import ROOT, guarded_files


def repo_markdown(exclude: Collection[Path] = (), root: Path = ROOT) -> list[Path]:
    """Every Markdown file of the repository but the hidden folders (which hold the skills'
    mirror), the vendored folders, the planning content and the excluded files and folders."""
    return [
        path
        for path in guarded_files(root, suffixes=[".md"])
        if path not in exclude and not any(folder in path.parents for folder in exclude)
    ]
