"""Run the clean and red checks against the tests commit.

The checks in `commit_order` and `red_check` ask about the tree as it stood at
the tests commit, before the implementation existed. That is not the tree the
agent is working in, so the commands run in a throwaway worktree checked out
at that commit — which also keeps the check from disturbing the agent's own
working directory.

Results are cached by **patch-id**, not by SHA. A restack rewrites every SHA
on the branch without changing a line of content; keying on the SHA would
re-run the checks on work already verified, on every push, forever.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.shell import git, git_out

WORKTREE_PREFIX = "spec-check-"

# A check that hasn't finished in this long isn't going to. The number is a
# starting point, to be revisited once real units have run.
COMMAND_TIMEOUT_SECONDS = 900


class CommandResult(Frozen):
    command: str
    exit_code: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


def patch_id(repo: Path, sha: str) -> str | None:
    """Content identity of a commit: stable across rebases, unlike the SHA."""
    try:
        show = git(repo, "show", sha)
        out = git(repo, "patch-id", "--stable", input=show.stdout).stdout.strip()
        return out.split()[0] if out else None
    except (subprocess.CalledProcessError, IndexError):
        return None


@contextmanager
def _worktree_at(repo: Path, sha: str):
    """A detached worktree at `sha`, removed however the block exits.

    Cleanup matters more than it looks: a leaked worktree makes every later
    run fail with "already exists", turning one bad run into all of them.
    """
    with tempfile.TemporaryDirectory(prefix=WORKTREE_PREFIX) as tmp:
        path = Path(tmp) / "tree"
        git_out(repo, "worktree", "add", "--detach", "-q", str(path), sha)
        try:
            yield path
        finally:
            git(repo, "worktree", "remove", "--force", str(path), check=False)
            git_out(repo, "worktree", "prune")


def run_at_commit(repo: Path, sha: str, commands: list[str]) -> list[CommandResult]:
    """Run each command in a worktree checked out at `sha`.

    A non-zero exit is data, not an error — the red check expects one — so
    results are returned rather than raised, and every command runs.
    """
    results: list[CommandResult] = []

    with _worktree_at(repo, sha) as tree:
        for command in commands:
            try:
                completed = subprocess.run(
                    command,
                    shell=True,
                    cwd=tree,
                    capture_output=True,
                    text=True,
                    timeout=COMMAND_TIMEOUT_SECONDS,
                    check=False,
                )
                results.append(
                    CommandResult(
                        command=command,
                        exit_code=completed.returncode,
                        stdout=completed.stdout,
                        stderr=completed.stderr,
                    )
                )
            except subprocess.TimeoutExpired:
                results.append(
                    CommandResult(
                        command=command,
                        exit_code=124,
                        stdout="",
                        stderr=f"timed out after {COMMAND_TIMEOUT_SECONDS}s",
                    )
                )

    return results


class CheckCache:
    """Remembers which commits have already been checked, by content.

    Keyed on patch-id so a restack — which rewrites SHAs but not content —
    doesn't invalidate work already verified. Failures are cached too:
    otherwise the slowest path, a broken commit, is the one re-run on every
    push.
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    def _load(self) -> dict[str, bool]:
        try:
            data = json.loads(self.path.read_text())
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}  # A corrupt cache is a miss, never a crash.

    def lookup(self, repo: Path, sha: str) -> bool | None:
        key = patch_id(repo, sha)
        return self._load().get(key) if key else None

    def record(self, repo: Path, sha: str, *, ok: bool) -> None:
        key = patch_id(repo, sha)
        if not key:
            return

        data = self._load()
        data[key] = ok
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2))
