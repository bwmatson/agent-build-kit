"""What `abk install-config` accepts and says, kept in one place.

The command (`cli/install_config.py`), the builders' prompts (`stack_runner.INSTALL_NOTE`) and
both runtimes' run-log lines read the same names and the same line, so a change to one cannot
leave another describing the old rule.
"""

from __future__ import annotations

import re
from pathlib import Path

# Where a builder stages a file, relative to its worktree.
STAGING = Path(".abk") / "proposed"

# The file names installable without `builders.installable_files`.
ALWAYS_INSTALLABLE = (".pre-commit-config.yaml",)

_INSTALLED = re.compile(r"installed (?P<target>.+) sha256=[0-9a-f]{64} size=\d+")


def install_line(target: str, sha256: str, size: int) -> str:
    """The line the command prints for an install: the target, the content hash and the size."""
    return f"installed {target} sha256={sha256} size={size}"


def logged_lines(text: str) -> list[str]:
    """The install lines in a command's output, for the unit's run log; other lines are not."""
    return [line for line in map(str.strip, text.splitlines()) if _INSTALLED.fullmatch(line)]
