"""The code a tick runs: its number, when it started and the kit checkout's head.

A tick loads the kit's modules once, at its start, so a merge made during a tick reaches only
a later one. The tick writes this record (`tick.json` in the state directory) before its first
round; `waiting_on` asks it whether a merge is in the code the tick runs.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from functools import cache
from pathlib import Path

from agent_build_kit.config import active_state_dir
from agent_build_kit.model import Frozen
from agent_build_kit.path_discovery import checkout_root
from agent_build_kit.pipeline.file_lock import atomic_write_text
from agent_build_kit.pipeline.shell import git

TICK_FILE = "tick.json"

# The directory the `agent_build_kit` package was imported from.
PACKAGE_DIR: Path = Path(__file__).resolve().parent.parent


@cache
def _is_ancestor(root: str, head: str, sha: str) -> bool:
    """Whether `sha` is in `head`'s history; a head never changes its ancestry, so git is
    asked once per triple."""
    return git(Path(root), "merge-base", "--is-ancestor", sha, head, check=False).returncode == 0


class LoadedCode(Frozen):
    """What a tick runs: its number, the kit's checkout and the head it read at start.

    `kit_repo` names the configured repo whose resolved path is the kit's work tree, None when
    no repo is; `kit_head` is None when the checkout's head could not be read."""

    number: int
    kit_repo: str | None = None
    kit_root: str | None = None
    kit_head: str | None = None

    def contains(self, merge_sha: str) -> bool | None:
        """Whether the head has the merge commit; None when the head or the checkout is
        unknown. A commit the checkout does not know is False."""
        if self.kit_head is None or self.kit_root is None:
            return None
        return _is_ancestor(self.kit_root, self.kit_head, merge_sha)

    def checkout_contains(self, merge_sha: str) -> bool:
        """Whether the checkout's head as it is now has the merge commit: what the next tick
        will load. False when the checkout is unknown or cannot be read."""
        if self.kit_root is None:
            return False
        found = git(Path(self.kit_root), "rev-parse", "HEAD", check=False)
        head = found.stdout.strip()
        return found.returncode == 0 and bool(head) and _is_ancestor(self.kit_root, head, merge_sha)


class TickRecord(LoadedCode):
    """The record `tick.json` holds: the loaded code and when the tick started."""

    started_at: datetime


# The record of the tick in this process, set by `cmd_tick` for the length of the tick.
_running: TickRecord | None = None


def running_tick(record: TickRecord | None) -> None:
    """Make `record` the code the tick of this process runs, or None once it has ended."""
    global _running
    _running = record


def read_record(path: Path) -> TickRecord | None:
    """The record in `path`; None when there is none or it cannot be read."""
    try:
        return TickRecord.model_validate_json(path.read_text())
    except (OSError, ValueError):
        return None


def current() -> TickRecord | None:
    """The code a tick runs: this process's tick, else the last record in the state directory
    of the active workspace; None when there is neither."""
    if _running is not None:
        return _running
    state_dir = active_state_dir()
    if state_dir is None:
        return None
    return read_record(state_dir / TICK_FILE)


def kit_checkout() -> Path | None:
    """The work tree the package was imported from; None when it is not in one."""
    return checkout_root(PACKAGE_DIR)


def start_record(state_dir: Path, checkouts: Mapping[str, Path]) -> TickRecord:
    """The record of a tick starting now: the last number plus one, the kit checkout, the
    configured repo it is, and its head (None when it cannot be read)."""
    last = read_record(state_dir / TICK_FILE)
    root = kit_checkout()
    repo = next((name for name, path in checkouts.items() if path.resolve() == root), None)
    head = None
    if root is not None:
        found = git(root, "rev-parse", "HEAD", check=False)
        head = found.stdout.strip() if found.returncode == 0 else None
    return TickRecord(
        number=(last.number if last else 0) + 1,
        started_at=datetime.now(UTC),
        kit_repo=repo,
        kit_root=str(root) if root else None,
        kit_head=head or None,
    )


def write_record(state_dir: Path, record: TickRecord) -> None:
    """Write the record atomically."""
    atomic_write_text(state_dir / TICK_FILE, record.model_dump_json())
