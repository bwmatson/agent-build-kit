"""The text edit behind `abk tags --fix`: the old test-kind tag of each group heading, renamed.

Only the tag inside a heading line the parser reads as a task-group heading is touched; every
other byte, line endings included, comes back as it was.
"""

from __future__ import annotations

from agent_build_kit.compat_names import Place, is_old_spelling, new_spelling
from agent_build_kit.pipeline.work_graph import GROUP_HEADING


def rewritten(text: str) -> tuple[str, int]:
    """`text` with the old test-kind tag of each group heading renamed, and how many were."""
    out: list[str] = []
    count = 0
    for line in text.splitlines(keepends=True):
        body = line.splitlines()[0]
        found = GROUP_HEADING.match(body)
        if found and is_old_spelling(Place.TAG, found["tier"]):
            start, end = found.span("tier")
            line = line[:start] + new_spelling(Place.TAG, found["tier"]) + line[end:]
            count += 1
        out.append(line)
    return "".join(out), count
