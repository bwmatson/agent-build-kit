"""What an agent call reports having spent, in the one shape every runtime fills."""

from __future__ import annotations

from enum import StrEnum
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


class ContextBasis(StrEnum):
    """How a record's context figures were obtained."""

    REPORTED = "reported"
    ESTIMATED = "estimated"
    UNKNOWN = "unknown"


class Context(BaseModel):
    """How full the model's context window was across one call, in tokens; a figure the
    runtime did not give is absent (None), never zero."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    used_start: Annotated[int | None, Salvaged] = None
    used_end: Annotated[int | None, Salvaged] = None
    added: Annotated[int | None, Salvaged] = None
    peak: Annotated[int | None, Salvaged] = None
    compactions: Annotated[int, Salvaged] = 0
    max: Annotated[int | None, Salvaged] = None
    basis: ContextBasis = ContextBasis.UNKNOWN


def context_of(
    fills: list[int],
    *,
    window: int | None,
    drop_share: float,
    basis: ContextBasis,
    markers: int = 0,
) -> Context | None:
    """The context use of a call whose requests left `fills` tokens in the window, in order;
    None when there is no request. A compaction is each of the runtime's own `markers`, and with
    none, each fall between consecutive requests larger than `drop_share` of the window (of
    the peak, where the window is not known). `basis` says where the window came from."""
    if not fills:
        return None
    reference = window or max(fills)
    drops = sum(1 for a, b in zip(fills, fills[1:], strict=False) if a - b > drop_share * reference)
    return Context(
        used_start=fills[0],
        used_end=fills[-1],
        added=max(fills[-1] - fills[0], 0),
        peak=max(fills),
        compactions=markers or drops,
        max=window,
        basis=basis if window else ContextBasis.UNKNOWN,
    )
