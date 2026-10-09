"""What a turn on a unit's own build session is told about the unit's change.

The change's proposal, design, spec deltas and the unit's task groups are given as read-only
context, with the rules for working on it: tests and code change together, and a request that
contradicts the change is flagged before anything is edited. The flag is a fenced
`spec-conflict` block holding JSON with the `requirement` and the `reason`, which the bridge
shows as a callout.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

from agent_build_kit.pipeline.units import Member

FLAG_FENCE = "spec-conflict"

GUIDANCE = f"""\
The change this unit builds is given below as context. It is read-only: never edit files
under the change's directory.

Change tests and code together in the same piece of work.

If a request contradicts a requirement or task below, do not edit anything. Reply first with a
flag naming the requirement or task, as a fenced block and nothing after it, then wait for the
user to confirm:

```{FLAG_FENCE}
{{"requirement": "<the requirement or task named>", "reason": "<how the request contradicts it>"}}
```
"""

_GROUP = re.compile(r"^## (\d+)\.", re.MULTILINE)


def _read(path: Path) -> str:
    try:
        return path.read_text().strip()
    except OSError:
        return ""


def _groups(tasks: str, wanted: Iterable[int]) -> str:
    """The sections of `tasks` for the groups numbered in `wanted`."""
    starts = [(m.start(), int(m.group(1))) for m in _GROUP.finditer(tasks)]
    keep = set(wanted)
    parts = []
    for index, (start, number) in enumerate(starts):
        end = starts[index + 1][0] if index + 1 < len(starts) else len(tasks)
        if number in keep:
            parts.append(tasks[start:end].strip())
    return "\n\n".join(parts)


def change_context(changes_dir: Path, members: Iterable[Member]) -> str:
    """The guidance and the files of each change the unit builds; empty when none is on disk."""
    sections: list[str] = []
    for member in members:
        change = changes_dir / member.change
        files = [
            ("proposal.md", _read(change / "proposal.md")),
            ("design.md", _read(change / "design.md")),
        ]
        files += [
            (f"specs/{spec.parent.name}/spec.md", _read(spec))
            for spec in sorted((change / "specs").glob("*/spec.md"))
        ]
        files.append(("task groups", _groups(_read(change / "tasks.md"), member.groups)))
        body = [f"### {name}\n\n{text}" for name, text in files if text]
        if body:
            sections.append(f"## Change {member.change}\n\n" + "\n\n".join(body))
    if not sections:
        return ""
    return GUIDANCE + "\n" + "\n\n".join(sections) + "\n\n---\n\n"
