"""Real git checkouts in temporary folders, for tests of what a unit changed."""

from collections.abc import Mapping
from pathlib import Path

from agent_build_kit.pipeline.shell import git
from tests.factories import init_repo


def write_files(repo: Path, files: Mapping[str, str]) -> None:
    """Write each file under `repo`, making its folders."""
    for name, text in files.items():
        target = repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)


def commit_files(repo: Path, files: Mapping[str, str], message: str = "change") -> None:
    """Write the files and commit everything in the working tree."""
    write_files(repo, files)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)


def repo_with_main(path: Path, files: Mapping[str, str]) -> Path:
    """A repository whose `main` holds `files` in one commit."""
    init_repo(path)
    commit_files(path, files, "base")
    return path


def fork_unit_branch(repo: Path, name: str = "unit") -> None:
    """Switch to a new branch forked from the current commit."""
    git(repo, "switch", "-q", "-c", name)
