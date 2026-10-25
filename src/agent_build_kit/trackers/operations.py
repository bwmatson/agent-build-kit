"""How each tracker operation may be repeated: one declaration per protocol method."""

from __future__ import annotations

from collections.abc import Mapping

from agent_build_kit.forges.operations import OperationSpec

_READ = OperationSpec(kind="read")
_WRITE = OperationSpec(kind="idempotent_write")

OPERATIONS: Mapping[str, OperationSpec] = {
    "capabilities": _READ,
    "identity": _READ,
    "get": _READ,
    "children": _READ,
    "changed_since": _READ,
    "find_by_marker": _READ,
    "update": _WRITE,
    "set_assignee": _WRITE,
    "link": _WRITE,
    "create": OperationSpec(kind="create", lands="find_by_marker"),
    # A comment cannot be looked up again, so it is retried and then contained.
    "comment": OperationSpec(kind="advisory"),
    "claim": OperationSpec(kind="claim"),
}
