"""Rebuild a repository's generated files after a restack and commit the result."""

import subprocess
from collections.abc import Sequence
from fnmatch import fnmatch
from pathlib import Path

from agent_build_kit.config import GeneratedConfig
from agent_build_kit.pipeline.shell import git


class GeneratedFilesFailed(RuntimeError):
    """A regenerate command exited non-zero; `output` is what it printed."""

    output: str

    def __init__(self, output: str) -> None:
        super().__init__(f"regenerating the generated files failed:\n{output}")
        self.output = output


def _matches(name: str, patterns: Sequence[str]) -> bool:
    return any(fnmatch(name, pattern) for pattern in patterns)


def regenerate(repo: Path, entries: Sequence[GeneratedConfig], *, onto: str) -> None:
    """Run each entry whose paths the unit's commits (`onto...HEAD`) touched, in its `cwd`,
    and commit what changed as one `chore:` commit. Raises `GeneratedFilesFailed`."""
    touched = git(repo, "diff", "--name-only", f"{onto}...HEAD").stdout.split()
    ran = False
    for entry in entries:
        if not any(_matches(name, entry.paths) for name in touched):
            continue
        done = subprocess.run(
            list(entry.command),
            cwd=repo / entry.cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        if done.returncode != 0:
            raise GeneratedFilesFailed((done.stdout + done.stderr).strip())
        ran = True
    if not ran:
        return
    git(repo, "add", "-A")
    if not git(repo, "diff", "--cached", "--name-only").stdout.strip():
        return
    git(
        repo,
        "commit",
        "--no-verify",
        "-q",
        "-m",
        f"chore: Rebuild the generated files after restacking onto {onto}",
    )
