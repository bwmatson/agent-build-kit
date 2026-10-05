"""A units file as the engine before the switch left it.

Nothing in a run writes `resume_from` or the in-run fields (review rounds,
deferred follow-ups, pending replies, the comments they answer) any more; only
a file written by an older version carries them, and `graph.convert` moves them
onto the unit's thread. A test that needs such a file writes it here, to the
file itself, since the store offers no way to.
"""

from __future__ import annotations

import json
from typing import Any

from agent_build_kit.pipeline.unit_store import UnitStore


def leave_in_flight(
    store: UnitStore, unit_id: str, *, resume_from: str = "", **in_run: Any
) -> None:
    """Write `resume_from` and any in-run field onto `unit_id`'s entry in the file."""
    raw = json.loads(store.path.read_text())
    for item in raw["units"]:
        if item["id"] == unit_id:
            if resume_from:
                item["resume_from"] = resume_from
            item.update(in_run)
    store.path.write_text(json.dumps(raw, indent=2) + "\n")
