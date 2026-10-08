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


OPERATIONS: Mapping[str, OperationSpec] = {}
