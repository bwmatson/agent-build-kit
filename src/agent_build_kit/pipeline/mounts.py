"""Which filesystem a path is on."""

from __future__ import annotations

import re
from pathlib import Path

from agent_build_kit.model import Frozen

MOUNTINFO = Path("/proc/self/mountinfo")

# Filesystems that are not a disk of this machine: network, host-shared and user-space ones.
_NOT_LOCAL = frozenset(
    {
        "nfs",
        "nfs4",
        "cifs",
        "smb3",
        "smbfs",
        "9p",
        "drvfs",
        "fuseblk",
        "virtiofs",
        "vboxsf",
        "ncpfs",
        "afs",
        "ceph",
        "glusterfs",
    }
)


class Mount(Frozen):
    fstype: str
    source: str
    options: str
    local: bool


def _unreadable(why: str) -> Mount:
    return Mount(fstype="unknown", source=why, options="", local=False)


def _unescape(field: str) -> str:
    """A mount point as `mountinfo` writes it: a space, tab or newline is an octal escape."""
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), field)


def mount_of(path: Path, table: str | None = None) -> Mount:
    """The mount holding `path`, read from `table` (the text of `mountinfo`) or, when none is
    given, from this machine's."""
    if table is None:
        try:
            table = MOUNTINFO.read_text(encoding="utf-8")
        except OSError as error:
            return _unreadable(f"{MOUNTINFO} unreadable: {error.strerror or error}")
    target = path.resolve()
    best: tuple[int, Mount] | None = None
    for line in table.splitlines():
        left, separator, right = line.partition(" - ")
        before, after = left.split(), right.split()
        if not separator or len(before) < 6 or len(after) < 2:
            continue
        point = Path(_unescape(before[4]))
        if target != point and point not in target.parents:
            continue
        if best is not None and len(point.parts) <= best[0]:
            continue
        fstype = after[0]
        options = ",".join([before[5], *after[2:3]])
        local = fstype not in _NOT_LOCAL and not fstype.startswith("fuse.")
        best = (
            len(point.parts),
            Mount(fstype=fstype, source=after[1], options=options, local=local),
        )
    if best is None:
        return _unreadable("no mount found in mountinfo")
    return best[1]
