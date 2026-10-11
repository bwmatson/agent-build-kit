"""What a change's spec said when an agent last ran, so a resumed session can be told what moved.

Copies of the files an agent is pointed at (the unit's groups of `tasks.md`, `design.md`,
`proposal.md`, `specs/**/spec.md`; never `follow-ups.md`) are kept under
`<state_dir>/spec-snapshots/<unit>/<role>/`, and a hash of them goes into the session's record.
Copies rather than git history, so an uncommitted edit is compared.
"""

from __future__ import annotations

import difflib
import hashlib
import re
import shutil
from collections.abc import Sequence
from pathlib import Path
from typing import NamedTuple

from agent_build_kit.pipeline.units import Member

SNAPSHOTS = "spec-snapshots"
DIFF_LIMIT = 6000
SPEC_CHANGED = """\
The change's spec was edited since your last turn. Changed: {names}.
Read it as it is now; what was added or altered:

```diff
{diff}
```
{rest}"""
REST_CUT = "(The diff is cut at {limit} characters; read the rest in {paths}.)\n"

_GROUP = re.compile(r"^##\s+(\d+)\.")


def _own_groups(text: str, groups: Sequence[int]) -> str:
    """The sections of `tasks.md` that belong to `groups`."""
    kept: list[str] = []
    current: int | None = None
    for line in text.splitlines(keepends=True):
        if found := _GROUP.match(line):
            current = int(found.group(1))
        if current in groups:
            kept.append(line)
    return "".join(kept)


class _Spec(NamedTuple):
    path: Path
    text: str  # as compared: for `tasks.md`, only the unit's own groups
    groups: Sequence[int]


def _named(members: Sequence[Member], change_dirs: Sequence[Path]) -> dict[str, _Spec]:
    """Each spec file the unit is pointed at, keyed by its path under its change (led by the
    change's name when the unit carries several)."""
    several = len(members) > 1
    found: dict[str, _Spec] = {}
    for member, change_dir in zip(members, change_dirs, strict=True):
        paths = [change_dir / "tasks.md", change_dir / "design.md", change_dir / "proposal.md"]
        paths += sorted((change_dir / "specs").glob("**/spec.md"))
        for path in paths:
            if not path.is_file():
                continue
            name = path.relative_to(change_dir).as_posix()
            text = path.read_text()
            if name == "tasks.md":
                text = _own_groups(text, member.groups)
            key = f"{member.change}/{name}" if several else name
            found[key] = _Spec(path, text, member.groups)
    return found


def snapshot_dir(state_dir: Path, unit_id: str, role: str) -> Path:
    return state_dir / SNAPSHOTS / unit_id / role


def forget(state_dir: Path, unit_id: str) -> None:
    """Remove every role's copies for a unit that is over."""
    shutil.rmtree(state_dir / SNAPSHOTS / unit_id, ignore_errors=True)


def save(
    state_dir: Path,
    unit_id: str,
    role: str,
    members: Sequence[Member],
    change_dirs: Sequence[Path],
) -> str:
    """Copy the unit's spec files for `role`, replacing the last copies; return their hash."""
    where = snapshot_dir(state_dir, unit_id, role)
    shutil.rmtree(where, ignore_errors=True)
    digest = hashlib.sha256()
    for key, spec in sorted(_named(members, change_dirs).items()):
        digest.update(f"{key}\0{spec.text}\0".encode())
        copy = where / key
        copy.parent.mkdir(parents=True, exist_ok=True)
        # The whole file is kept; only the compared sections go into the hash and the diff.
        copy.write_text(spec.path.read_text())
    where.mkdir(parents=True, exist_ok=True)
    return digest.hexdigest()


def notice(
    state_dir: Path,
    unit_id: str,
    role: str,
    recorded: str,
    members: Sequence[Member],
    change_dirs: Sequence[Path],
) -> str:
    """What to say to a resumed session about the spec files that differ from its copies;
    empty when nothing differs, or when no copies were recorded for it."""
    if not recorded:
        return ""
    where = snapshot_dir(state_dir, unit_id, role)
    changed: list[str] = []
    places: list[Path] = []
    diffs: list[str] = []
    for key, spec in sorted(_named(members, change_dirs).items()):
        copy = where / key
        before = copy.read_text() if copy.is_file() else ""
        if key.rsplit("/", 1)[-1] == "tasks.md":
            before = _own_groups(before, spec.groups)
        if before == spec.text:
            continue
        changed.append(key)
        places.append(spec.path)
        lines = difflib.unified_diff(
            before.splitlines(keepends=True),
            spec.text.splitlines(keepends=True),
            fromfile=key,
            tofile=key,
            n=1,
        )
        diffs.append("".join(lines))
    if not changed:
        return ""
    diff = "".join(diffs)
    rest = ""
    if len(diff) > DIFF_LIMIT:
        diff = diff[:DIFF_LIMIT]
        rest = REST_CUT.format(limit=DIFF_LIMIT, paths=", ".join(str(p) for p in places))
    return SPEC_CHANGED.format(names=", ".join(changed), diff=diff.rstrip("\n"), rest=rest)
