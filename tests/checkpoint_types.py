"""What a unit graph's checkpoint holds, read from the file a run left.

The values are taken from the saver's own tables, before any allowlist reads
them back: a type a checkpoint refuses to load is turned into text on the way
out, so only the bytes on disk show it was there.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from typing import Any

import ormsgpack
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from agent_build_kit.graph.checkpointer import ALLOWED_MSGPACK_MODULES

# Constructor, method and pydantic encodings: the data is (module, name, ...).
_TYPED_EXTENSIONS = range(6)


def _named_types(blob: bytes) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()

    def hook(code: int, data: bytes) -> Any:
        inner = ormsgpack.unpackb(data, ext_hook=hook, option=ormsgpack.OPT_NON_STR_KEYS)
        if code in _TYPED_EXTENSIONS:
            found.add((inner[0], inner[1]))
        return inner

    ormsgpack.unpackb(blob, ext_hook=hook, option=ormsgpack.OPT_NON_STR_KEYS)
    return found


def types_off_the_list(value: Any) -> set[tuple[str, str]]:
    """The (module, name) of every type `value` is encoded as that a checkpoint may not load.

    The standard library's and the graph library's own types are the library's to load.
    """
    kind, blob = JsonPlusSerializer(
        allowed_msgpack_modules=list(ALLOWED_MSGPACK_MODULES)
    ).dumps_typed(value)
    if kind != "msgpack":
        return set()
    return {
        named
        for named in _named_types(blob)
        if named[0].split(".")[0] not in {*sys.stdlib_module_names, "langgraph"}
        and named not in ALLOWED_MSGPACK_MODULES
    }


def node_updates(db: Path) -> list[tuple[str, Any]]:
    """Every (field, value) the nodes of a run wrote, as the objects they returned."""
    serde = JsonPlusSerializer(allowed_msgpack_modules=True)
    with sqlite3.connect(db) as conn:
        rows = conn.execute("SELECT channel, type, value FROM writes ORDER BY rowid").fetchall()
    return [(channel, serde.loads_typed((kind, value))) for channel, kind, value in rows]


def blocked_in_updates(db: Path) -> list[str]:
    """`field: module.Name` for each value a node wrote that the checkpoint would block."""
    return [
        f"{channel}: {module}.{name}"
        for channel, value in node_updates(db)
        for module, name in sorted(types_off_the_list(value))
    ]
