"""Rebuild a repository's generated files after a restack and commit the result."""

import subprocess
from collections.abc import Sequence
from pathlib import Path

from agent_build_kit.budget import cut_head
from agent_build_kit.config import GeneratedConfig
from agent_build_kit.pipeline.check_runner import COMMAND_TIMEOUT_SECONDS
from agent_build_kit.pipeline.shell import git
from agent_build_kit.pipeline.unit_size import is_generated


class GeneratedFilesFailed(RuntimeError):
    """A regenerate command could not run, timed out or exited non-zero; `output` says why."""

    output: str

    def __init__(self, output: str) -> None:
        super().__init__(f"regenerating the generated files failed:\n{output}")
        self.output = output


def hold_note(onto: str, error: GeneratedFilesFailed) -> str:
    """The note a unit is held with when its generated files could not be rebuilt: the one
    text every restack path records under the `generated_files` cause."""
    return (
        f"rebuilding the generated files after restacking onto {onto} failed:\n"
        f"{cut_head(error.output, 1000, 'char')}"
    )


def _changed_under(repo: Path, patterns: Sequence[str]) -> list[str]:
    """Paths the working tree modifies, deletes or adds that `patterns` cover."""
    listed = git(
        repo, "ls-files", "-z", "--modified", "--deleted", "--others", "--exclude-standard"
    ).stdout
    return sorted({name for name in listed.split("\0") if name and is_generated(name, patterns)})


def discard_output(repo: Path, entries: Sequence[GeneratedConfig]) -> None:
    """Remove what a failed command left under its entries' paths: edits and new files."""
    left = _changed_under(repo, [pattern for entry in entries for pattern in entry.paths])
    if left:
        git(repo, "checkout", "-q", "HEAD", "--", *left, check=False)
        git(repo, "clean", "-fdq", "--", *left, check=False)


def regenerate(
    repo: Path,
    entries: Sequence[GeneratedConfig],
    *,
    onto: str,
    timeout: float = COMMAND_TIMEOUT_SECONDS,
) -> None:
    """Run each entry whose paths the unit's commits (`onto...HEAD`) touched, in its `cwd`,
    and commit what changed under those entries' paths as one `chore:` commit. A command that
    cannot start, runs past `timeout` seconds or exits non-zero raises `GeneratedFilesFailed`."""
    touched = git(repo, "diff", "--name-only", f"{onto}...HEAD").stdout.split()
    ran: list[GeneratedConfig] = []
    for entry in entries:
        if not any(is_generated(name, entry.paths) for name in touched):
            continue
        shown = " ".join(entry.command)
        try:
            done = subprocess.run(
                list(entry.command),
                cwd=repo / entry.cwd,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout,
            )
        except OSError as error:
            raise GeneratedFilesFailed(f"`{shown}` could not be run: {error}") from error
        except subprocess.TimeoutExpired as error:
            raise GeneratedFilesFailed(f"`{shown}` timed out after {timeout:g}s") from error
        if done.returncode != 0:
            raise GeneratedFilesFailed((done.stdout + done.stderr).strip())
        ran.append(entry)
    if not ran:
        return
    changed = _changed_under(repo, [pattern for entry in ran for pattern in entry.paths])
    if not changed:
        return
    git(repo, "add", "-A", "--", *changed)
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
