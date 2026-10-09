"""The lease on a unit: who is chatting with it, which the tick respects.

While a holder has a unit's lease no step starts on it; releasing the lease returns the
unit to the tick, which resumes from the recorded node. A lease names the process that took
it, so one left by a process that has since died (a crashed or restarted server) holds
nothing.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.file_lock import file_lock


def lease_dir(state_dir: Path) -> Path:
    """The directory of its own, under the state directory."""
    return state_dir / "leases"


def _started(pid: int) -> str | None:
    """When the process began, in the kernel's ticks, or None if there is no such process.
    The pair (pid, start) names one process for good; a pid alone can be reused."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    # The command name, in parentheses, may itself hold spaces and parentheses.
    return stat[stat.rindex(")") + 2 :].split()[19]


class Attachment(Frozen):
    """What a lease records beyond its holder: the checkouts a chat covers, how many files
    they hold uncommitted, the session and runtime, the branch head when it was taken, and
    the commit made and not yet delivered. `stale` is a lease whose process has gone."""

    unit_id: str
    holder: str
    checkouts: tuple[str, ...] = ()
    changed: int = 0
    session: str = ""
    runtime: str = ""
    head: str = ""
    committed: str = ""
    stale: bool = False


class Leases:
    """The leases under `directory`, one file per unit, shared by every process."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory

    def _path(self, unit_id: str) -> Path:
        return self._directory / (unit_id.replace("/", "--") + ".lease")

    def _guard(self):
        return file_lock(self._directory / ".lock")

    def _read(self, path: Path) -> str | None:
        """The holder named in `path`, unless the process that took it is gone."""
        try:
            record = json.loads(path.read_text())
            holder, pid, started = record["holder"], int(record["pid"]), record["started"]
        except (OSError, ValueError, KeyError, TypeError):
            return None
        return holder if holder and _started(pid) == started else None

    def take(
        self,
        unit_id: str,
        holder: str,
        *,
        checkouts: tuple[str, ...] = (),
        session: str = "",
        runtime: str = "",
        head: str = "",
    ) -> bool:
        """Take the unit's lease for `holder`; True also when `holder` already has it,
        False while another holds it."""
        with self._guard():
            held = self._read(self._path(unit_id))
            if held not in (None, holder):
                return False
            pid = os.getpid()
            record = {"holder": holder, "pid": pid, "started": _started(pid)}
            self._path(unit_id).write_text(json.dumps(record))
            return True

    def release(self, unit_id: str, holder: str) -> None:
        """Give the lease up. A holder that does not hold it changes nothing."""
        with self._guard():
            if self._read(self._path(unit_id)) == holder:
                self._path(unit_id).unlink(missing_ok=True)

    def holder(self, unit_id: str) -> str | None:
        return self._read(self._path(unit_id))

    def release_all(self, holder: str) -> None:
        """Release every lease `holder` has, as a page closing does."""
        with self._guard():
            for path in self._directory.glob("*.lease"):
                if self._read(path) == holder:
                    path.unlink(missing_ok=True)

    def mark_changes(self, unit_id: str, holder: str, files: int) -> None:
        """Record that the covered checkouts hold `files` uncommitted files (none clears it)."""
        raise NotImplementedError

    def mark_committed(self, unit_id: str, holder: str, commit: str) -> None:
        """Record a commit made and not yet delivered."""
        raise NotImplementedError

    def attachment(self, unit_id: str) -> Attachment | None:
        """The unit's lease with what it records: live, or stale while it holds changes or a
        commit not delivered; None when it holds nothing."""
        raise NotImplementedError

    def attachments(self) -> list[Attachment]:
        """Every attachment, live or stale."""
        raise NotImplementedError
