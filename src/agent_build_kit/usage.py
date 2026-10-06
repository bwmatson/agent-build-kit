"""What an agent call reports having spent, in the one shape every runtime fills."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, WrapValidator
from pydantic_core.core_schema import ValidatorFunctionWrapHandler

# Where a figure came from: the gateway's own records for the run's key, the
# agent's own report, an approximation flagged as one, or nothing at all.
UsageSource = Literal["gateway", "reported", "estimated", "none"]


def _salvage(value: Any, handler: ValidatorFunctionWrapHandler) -> Any:
    try:
        return handler(value)
    except ValidationError:
        return None


# A figure that is not the type it should be reads as absent: recording what a
# run spent never changes how the run is read, so one drifted figure must not
# cost the payload around it.
Salvaged = WrapValidator(_salvage)


class Usage(BaseModel):
    """Tokens by kind, each absent (None) when the agent did not say — never zero.

    Not `model.Frozen`: the payloads this is read from (a result event, an ACP
    response) carry fields a later version adds, and none is a reason to lose
    the counts that are there.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    input_tokens: Annotated[int | None, Field(ge=0), Salvaged] = None
    output_tokens: Annotated[int | None, Field(ge=0), Salvaged] = None
    cache_read_input_tokens: Annotated[int | None, Field(ge=0), Salvaged] = None
    cache_creation_input_tokens: Annotated[int | None, Field(ge=0), Salvaged] = None
