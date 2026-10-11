"""What a change's spec said when an agent last ran, so a resumed session can be told what moved.

Copies of the files an agent is pointed at (the unit's groups of `tasks.md`, `design.md`,
`proposal.md`, `specs/**/spec.md`; never `follow-ups.md`) are kept under
`<state_dir>/spec-snapshots/<unit>/<role>/`, and a hash of them goes into the session's record.
Copies rather than git history, so an uncommitted edit is compared.
"""

from __future__ import annotations

import difflib
import hashlib
import shutil
from collections.abc import Sequence
from pathlib import Path
from typing import NamedTuple

from agent_build_kit.pipeline.task_progress import without_boxes
from agent_build_kit.pipeline.units import Member
from agent_build_kit.pipeline.work_graph import group_sections

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


def _compared(name: str, text: str, groups: Sequence[int]) -> str:
    """The text of a spec file as compared: for `tasks.md`, only the unit's own groups, with
    their boxes in one form, since the pipeline ticks and unticks those itself."""
    if name.rsplit("/", 1)[-1] != "tasks.md":
        return text
    return without_boxes("".join(group_sections(text, groups)))


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
            text = _compared(name, path.read_text(), member.groups)
            key = f"{member.change}/{name}" if several else name
            found[key] = _Spec(path, text, member.groups)
    return found


def _digest(named: dict[str, _Spec]) -> str:
    digest = hashlib.sha256()
    for key, spec in sorted(named.items()):
        digest.update(f"{key}\0{spec.text}\0".encode())
    return digest.hexdigest()


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
    named = _named(members, change_dirs)
    for key, spec in sorted(named.items()):
        copy = where / key
        copy.parent.mkdir(parents=True, exist_ok=True)
        # The whole file is kept; only the compared sections go into the hash and the diff.
        copy.write_text(spec.path.read_text())
    where.mkdir(parents=True, exist_ok=True)
    return _digest(named)


def notice(
    state_dir: Path,
    unit_id: str,
    role: str,
    recorded: str,
    members: Sequence[Member],
    change_dirs: Sequence[Path],
) -> str:
    """What to say to a resumed session about the spec files that differ from its copies;
    empty when nothing differs, or when no copies were recorded for it or they are gone."""
    where = snapshot_dir(state_dir, unit_id, role)
    if not recorded or not where.is_dir():
        return ""
    named = _named(members, change_dirs)
    if _digest(named) == recorded:
        return ""
    changed: list[str] = []
    places: list[Path] = []
    diffs: list[str] = []
    for key, spec in sorted(named.items()):
        copy = where / key
        before = _compared(key, copy.read_text(), spec.groups) if copy.is_file() else ""
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
