"""Each agent run's ignored scratch folder for long command output.

The folder is `<worktree>/.abk/out/<run>/`, excluded from git through the
worktree's local exclude file, owned by one run and removed when it ends
(docs/architecture.md).
"""

from __future__ import annotations

import shutil
import subprocess
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from agent_build_kit.pipeline.shell import git_out

SCRATCH = Path(".abk") / "out"
EXCLUDE_LINE = ".abk/"

# A file in a run's folder is cut to this much of its tail.
MAX_BYTES = 5_000_000
# How often a live run's folder is checked against the cap.
CAP_INTERVAL = 2.0

CONVENTION = """\
Long command output goes to a file, not into your context. Redirect a command
that may print a lot, and its exit status, into `$ABK_OUT/`:

    <command> > "$ABK_OUT/<name>.log" 2>&1; echo $? > "$ABK_OUT/<name>.exit"

Name the files by what produced them (`suite.log`, `lint.log`) and read them
with `tail`, `grep` or `sed -n`. Never run a command again to see more of its
output: the file already holds it. If the file lacks what you need, rerun with
a narrower scope rather than the same command. Run the full suite once, after
your last edit of the round; after a fix, run only the tests that failed. The
folder is yours alone, ignored by git, and removed when your run ends, so
nothing in it is part of your work.
"""


def output_convention() -> str:
    """The packaged prompt text that tells an agent to keep long command output in
    `$ABK_OUT` and read it from there."""
    return CONVENTION


def scratch_folder(worktree: Path) -> Path:
    return worktree / SCRATCH


def carries_scratch(checkout: Path) -> bool:
    """Whether `checkout` has a scratch folder: a unit's run is in it, so the
    redirect rule (`command_policy`) covers it. Both runtimes ask this."""
    return scratch_folder(checkout).is_dir()


def _is_checkout(path: Path) -> bool:
    try:
        git_out(path, "rev-parse", "--git-dir")
    except (OSError, subprocess.CalledProcessError):
        return False
    return True


def ensure_scratch(worktree: Path) -> None:
    """The worktree's scratch folder, with its exclude line in place once.

    The line goes in the repository's local `info/exclude`, never a tracked
    ignore file, so no commit or diff changes.
    """
    scratch_folder(worktree).mkdir(parents=True, exist_ok=True)
    exclude = Path(
        git_out(worktree, "rev-parse", "--path-format=absolute", "--git-path", "info/exclude")
    )
    text = exclude.read_text() if exclude.exists() else ""
    if EXCLUDE_LINE in (line.strip() for line in text.splitlines()):
        return
    exclude.parent.mkdir(parents=True, exist_ok=True)
    separator = "" if not text or text.endswith("\n") else "\n"
    exclude.write_text(f"{text}{separator}{EXCLUDE_LINE}\n")


def _marker(max_bytes: int) -> bytes:
    return f"[truncated: only the last {max_bytes} bytes are kept]\n".encode()


def cap_files(folder: Path, *, max_bytes: int) -> None:
    """Truncate each file in `folder` larger than `max_bytes` to its tail, led by a marker.

    The marker and the tail together fit `max_bytes`, so a cut file is within the
    limit and is left alone by the next pass; a file that already begins with the
    marker and is within the limit is never rewritten.

    A file is rewritten in place, so a command still holding it open sees it
    shrink. A writer that opened it with a plain `>` keeps its old offset, and
    its next write leaves a hole of NUL bytes before it; the next pass drops
    those, so the agent reads the marker and the last lines written, and the
    hole costs no disk (it is sparse).
    """
    marker = _marker(max_bytes)
    keep = max(max_bytes - len(marker), 0)
    for path in folder.rglob("*"):
        try:
            if not path.is_file() or path.stat().st_size <= max_bytes:
                continue
            with path.open("r+b") as file:
                file.seek(-keep if keep else 0, 2)
                tail = file.read().replace(b"\0", b"")
                # Start on a whole line: the first one is cut anywhere.
                _, newline, rest = tail.partition(b"\n")
                file.seek(0)
                file.write(marker + (rest if newline else tail))
                file.truncate()
        except OSError:
            # Gone or replaced under us; the next pass sees what is left.
            continue


def remove_leftovers(worktree: Path) -> None:
    """Remove every run folder under the worktree's scratch folder: what killed runs left."""
    folder = scratch_folder(worktree)
    if not folder.is_dir():
        return
    for entry in folder.iterdir():
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry, ignore_errors=True)
        else:
            entry.unlink(missing_ok=True)


@contextmanager
def watch_folder(folder: Path, *, max_bytes: int, interval: float) -> Iterator[threading.Event]:
    """Run `cap_files` over `folder` every `interval` seconds until the block ends,
    yielding an event set after each pass: a test clears it and waits on it instead of
    polling the folder."""
    done = threading.Event()
    passed = threading.Event()

    def enforce() -> None:
        while not done.wait(interval):
            cap_files(folder, max_bytes=max_bytes)
            passed.set()

    thread = threading.Thread(target=enforce, daemon=True)
    thread.start()
    try:
        yield passed
    finally:
        done.set()
        thread.join()


@contextmanager
def run_folder(
    worktree: Path, *, max_bytes: int | None = None, interval: float | None = None
) -> Iterator[Path | None]:
    """A new empty folder for one agent run, removed when the run ends however it ends.

    What an earlier killed run left is removed first. While the run goes, a file
    in it past `max_bytes` is cut to its tail every `interval` seconds, so one
    runaway command cannot fill the disk. A directory that is not a git checkout
    has no scratch folder: this yields None.

    Runs in one worktree are serialized (the branch lock), so clearing every
    earlier run folder is safe; a run overlapping another in the same worktree
    would lose its live folder.
    """
    if not _is_checkout(worktree):
        yield None
        return
    ensure_scratch(worktree)
    remove_leftovers(worktree)
    folder = scratch_folder(worktree) / uuid.uuid4().hex[:12]
    folder.mkdir()
    cap = MAX_BYTES if max_bytes is None else max_bytes
    pause = CAP_INTERVAL if interval is None else interval

    try:
        with watch_folder(folder, max_bytes=cap, interval=pause):
            yield folder
    finally:
        shutil.rmtree(folder, ignore_errors=True)
