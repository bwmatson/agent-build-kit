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
from typing import Any

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

    def _load(self, path: Path) -> dict[str, Any] | None:
        """The record in `path`, whether or not its process is alive."""
        try:
            record = json.loads(path.read_text())
            if not record["holder"]:
                return None
            int(record["pid"])
            record["started"]
        except (OSError, ValueError, KeyError, TypeError):
            return None
        return record if isinstance(record, dict) else None

    @staticmethod
    def _alive(record: dict[str, Any]) -> bool:
        return _started(int(record["pid"])) == record["started"]

    def _read(self, path: Path) -> str | None:
        """The holder named in `path`, unless the process that took it is gone."""
        record = self._load(path)
        return record["holder"] if record and self._alive(record) else None

    def _write(self, unit_id: str, record: dict[str, Any]) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)
        self._path(unit_id).write_text(json.dumps(record))

    def _attachment(self, unit_id: str, record: dict[str, Any]) -> Attachment | None:
        alive = self._alive(record)
        changed = int(record.get("changed", 0))
        committed = str(record.get("committed", ""))
        if not alive and not changed and not committed:
            return None
        return Attachment(
            unit_id=unit_id,
            holder=record["holder"],
            checkouts=tuple(record.get("checkouts", ())),
            changed=changed,
            session=record.get("session", ""),
            runtime=record.get("runtime", ""),
            head=record.get("head", ""),
            committed=committed,
            stale=not alive,
        )

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
        False while another holds it. A lease left with changes or an undelivered commit
        keeps them when it is taken."""
        with self._guard():
            old = self._load(self._path(unit_id)) or {}
            if old and self._alive(old) and old["holder"] != holder:
                return False
            pid = os.getpid()
            record = {
                "holder": holder,
                "pid": pid,
                "started": _started(pid),
                "checkouts": list(checkouts or old.get("checkouts", ())),
                "changed": old.get("changed", 0),
                "session": session or old.get("session", ""),
                "runtime": runtime or old.get("runtime", ""),
                "head": head or old.get("head", ""),
                "committed": old.get("committed", ""),
            }
            self._write(unit_id, record)
            return True

    def release(self, unit_id: str, holder: str) -> None:
        """Give the lease up. A holder that does not hold it changes nothing."""
        with self._guard():
            if self._read(self._path(unit_id)) == holder:
                self._path(unit_id).unlink(missing_ok=True)

    def drop(self, unit_id: str) -> None:
        """Remove the unit's lease whoever holds it, once what it held is resolved."""
        with self._guard():
            self._path(unit_id).unlink(missing_ok=True)

    def hand_over(self, unit_id: str, old: str, new: str) -> None:
        """Move a lease `old` holds to `new`, keeping what it records."""
        with self._guard():
            record = self._load(self._path(unit_id))
            if record and self._alive(record) and record["holder"] == old:
                pid = os.getpid()
                self._write(
                    unit_id, {**record, "holder": new, "pid": pid, "started": _started(pid)}
                )

    def holder(self, unit_id: str) -> str | None:
        return self._read(self._path(unit_id))

    def release_all(self, holder: str) -> None:
        """Release every lease `holder` has that holds nothing, as a page closing does."""
        with self._guard():
            for path in self._directory.glob("*.lease"):
                record = self._load(path)
                if (
                    record
                    and self._alive(record)
                    and record["holder"] == holder
                    and not record.get("changed")
                    and not record.get("committed")
                ):
                    path.unlink(missing_ok=True)

    def _update(self, unit_id: str, holder: str, *, alive: bool = True, **fields: Any) -> None:
        with self._guard():
            record = self._load(self._path(unit_id))
            if record and (self._alive(record) or not alive) and record["holder"] == holder:
                self._write(unit_id, {**record, **fields})

    def mark_changes(self, unit_id: str, holder: str, files: int) -> None:
        """Record that the covered checkouts hold `files` uncommitted files (none clears it)."""
        self._update(unit_id, holder, changed=files)

    def mark_committed(self, unit_id: str, holder: str, commit: str) -> None:
        """Record a commit made and not yet delivered, whether or not its process is alive."""
        self._update(unit_id, holder, alive=False, committed=commit, changed=0)

    def release_checkout(self, unit_id: str, checkout: str) -> None:
        """Drop one checkout from the lease's part; the lease goes with its last when it holds
        no changes and no commit."""
        with self._guard():
            record = self._load(self._path(unit_id))
            if record is None:
                return
            left = [c for c in record.get("checkouts", ()) if c != checkout]
            if not left and not record.get("changed") and not record.get("committed"):
                self._path(unit_id).unlink(missing_ok=True)
            else:
                self._write(unit_id, {**record, "checkouts": left})

    def attachment(self, unit_id: str) -> Attachment | None:
        """The unit's lease with what it records: live, or stale while it holds changes or a
        commit not delivered; None when it holds nothing."""
        record = self._load(self._path(unit_id))
        return self._attachment(unit_id, record) if record else None

    def attachments(self) -> list[Attachment]:
        """Every attachment, live or stale."""
        found = []
        for path in sorted(self._directory.glob("*.lease")):
            record = self._load(path)
            unit_id = path.stem.replace("--", "/")
            if record and (item := self._attachment(unit_id, record)):
                found.append(item)
        return found
