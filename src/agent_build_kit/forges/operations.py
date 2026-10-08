"""How each forge operation may be repeated: one declaration per protocol method.

A `read` and an `idempotent_write` are repeated on a transient failure. A
`create` is repeated only after the read named in `lands` shows it did not land.
An `advisory` call is retried and then contained: it logs, counts and returns
its neutral value instead of raising.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from agent_build_kit.model import Frozen

OperationKind = Literal["read", "idempotent_write", "create", "advisory"]


class OperationSpec(Frozen):
    kind: OperationKind
    # For a create: the protocol read that shows whether it landed.
    lands: str | None = None


_READ = OperationSpec(kind="read")
_WRITE = OperationSpec(kind="idempotent_write")

OPERATIONS: Mapping[str, OperationSpec] = {
    "parse_remote": _READ,
    "identity": _READ,
    "config_entry": _READ,
    "web_url": _READ,
    "check_access": _READ,
    "access_fix": _READ,
    "merge_guard": _READ,
    "find_pr": _READ,
    "list_prs": _READ,
    "pr_files": _READ,
    "pr_changes": _READ,
    "review_notes": _READ,
    "stack_of": _READ,
    "failed_check_logs": _READ,
    "update_pr": _WRITE,
    "post_status": _WRITE,
    "close_pr": _WRITE,
    "rerun_checks": _WRITE,
    "delete_remote_branch": _WRITE,
    "add_label": _WRITE,
    "set_exclusive_label": _WRITE,
    "remove_label": _WRITE,
    "create_pr": OperationSpec(kind="create", lands="find_pr"),
    "post_comment": OperationSpec(kind="create", lands="comment_exists"),
    "post_reply": OperationSpec(kind="create", lands="comment_exists"),
    "create_stack": OperationSpec(kind="create", lands="stack_of"),
    "add_to_stack": OperationSpec(kind="create", lands="stack_of"),
    "set_draft": OperationSpec(kind="advisory"),
}
