"""What a unit graph's checkpoint holds, and what the library would refuse to load of it.

Blocking is decided by the library itself: its serde events are listened to as
a value is read back through the checkpointer's own serializer and allowed
list, so there is no second copy of the rule here. The values nodes wrote are
taken from the saver's tables, before any allowlist reads them back: a type a
checkpoint refuses to load is turned into text on the way out.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from langgraph.checkpoint.serde.event_hooks import SerdeEvent, register_serde_event_listener
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from agent_build_kit.graph.checkpointer import ALLOWED_MSGPACK_MODULES

BLOCKED_KINDS = frozenset({"msgpack_blocked", "msgpack_method_blocked"})


@contextmanager
def blocked_while_reading() -> Iterator[set[tuple[str, str]]]:
    """The (module, name) of each type the library blocks, filled in as the body reads."""
    blocked: set[tuple[str, str]] = set()

    def listen(event: SerdeEvent) -> None:
        if event["kind"] in BLOCKED_KINDS:
            blocked.add((event["module"], event["name"]))

    unregister = register_serde_event_listener(listen)
    try:
        yield blocked
    finally:
        unregister()


def blocked_on_load(value: Any) -> set[tuple[str, str]]:
    """The types in `value` that the checkpoint's serializer, with the allowed list, would block."""
    serde = JsonPlusSerializer(allowed_msgpack_modules=list(ALLOWED_MSGPACK_MODULES))
    with blocked_while_reading() as blocked:
        serde.loads_typed(serde.dumps_typed(value))
    return blocked


def node_updates(db: Path) -> list[tuple[str, Any]]:
    """Every (field, value) the nodes of a run wrote, as the objects they returned."""
    serde = JsonPlusSerializer(allowed_msgpack_modules=True)
    with sqlite3.connect(db) as conn:
        rows = conn.execute("SELECT channel, type, value FROM writes ORDER BY rowid").fetchall()
    return [(channel, serde.loads_typed((kind, value))) for channel, kind, value in rows]


def blocked_in(updates: list[tuple[str, Any]]) -> list[str]:
    """`field: module.Name` for each value in `updates` that the checkpoint would block."""
    return [
        f"{field}: {module}.{name}"
        for field, value in updates
        for module, name in sorted(blocked_on_load(value))
    ]
