"""The before-and-after comparison of a reorganization's test files (standard T26)."""

from pathlib import Path

from agent_build_kit.model import Frozen

STANDARD = "T26"


class Finding(Frozen):
    """One way a changed test file differs from its parent's version beyond a mechanical edit."""

    standard: str
    path: str
    test: str
    reason: str


def compare_sources(before: str, after: str) -> list[Finding]:
    """Findings for one Python test file, read by AST, with renamed imports and names normalised."""
    raise NotImplementedError


def compare_changes(repo: Path, base: str, head: str = "HEAD") -> list[Finding]:
    """Findings for every test file changed between `base` and `head`, following git renames."""
    raise NotImplementedError
