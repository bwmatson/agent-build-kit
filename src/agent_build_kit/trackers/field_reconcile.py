"""The three-way reconcile of one field of one item: the last-synced snapshot, the spec's
value and the tracker's value."""

from __future__ import annotations

from typing import Literal

from agent_build_kit.model import Frozen

# Text fields follow the spec on a clash; the others follow the tracker.
TEXT_FIELDS = ("title", "body")
Action = Literal["tracker", "outbound", "none", "spec"]


class FieldConflict(Frozen):
    """Both sides changed a field to different values; `kept` is the side that won."""

    field: str
    spec_value: str
    tracker_value: str
    kept: Literal["spec", "tracker"]
    spec_who: str
    tracker_who: str


class FieldOutcome(Frozen):
    """What to do with a field: `tracker` take the board's value, `outbound` leave the spec's
    value for the outbound pass, `none` nothing, `spec` keep the spec's value over a clash."""

    action: Action
    value: str
    conflict: FieldConflict | None = None


def reconcile_field(
    field: str,
    base: str,
    spec: str,
    tracker: str,
    *,
    spec_who: str = "spec",
    tracker_who: str = "",
) -> FieldOutcome:
    raise NotImplementedError
