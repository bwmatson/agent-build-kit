"""Ticking a unit's tasks off in its change's `tasks.md` — by the pipeline.

The build agents used to tick boxes themselves as they worked, following
OpenSpec's own apply flow. That marks a group done after its first build,
before any review; when the review loop then fails it and the work is never
pushed, the file still says it was finished. Now agents may
not write to the planning repo at all (the policy hook refuses it), and a
unit's groups are ticked when it reaches `in_review` — through the build/review
loop, tier 1 and the push — and unticked if it fails.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

from agent_build_kit.pipeline.file_lock import file_lock


def mark_groups(tasks: Path, groups: Iterable[int], *, done: bool) -> None:
    """Set every task box in `groups` to done or not done.

    Only the boxes: the text is left exactly as it was. Locked, because units
    in parallel share one change's file.
    """
    numbers = "|".join(str(group) for group in groups)
    if not numbers or not tasks.exists():
        return
    box = re.compile(rf"^(\s*- )\[[ xX]\]( (?:{numbers})\.\d+ )", re.M)
    mark = "x" if done else " "
    with file_lock(tasks.with_name(f"{tasks.name}.lock")):
        text = tasks.read_text()
        updated = box.sub(rf"\g<1>[{mark}]\g<2>", text)
        if updated != text:
            tasks.write_text(updated)
