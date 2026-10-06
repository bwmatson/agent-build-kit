"""What an agent call reports having spent, in the one shape every runtime fills."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

# Where a figure came from: the agent's own report, an approximation flagged as
# one, or nothing at all.
UsageSource = Literal["reported", "estimated", "none"]


class Usage(BaseModel):
    """Tokens by kind, each absent (None) when the agent did not say — never zero.

    Not `model.Frozen`: the payloads this is read from (a result event, an ACP
    response) carry fields a later version adds, and none is a reason to lose
    the counts that are there.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_input_tokens: int | None = None
    cache_creation_input_tokens: int | None = None
