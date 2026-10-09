"""The names and colours of a unit's states, in one place.

The unit graph draws them and a pull request's labels carry them, so both read
this rather than each keeping a copy that can drift.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from agent_build_kit.forges import Label
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.unit_store import UNPLANNED, Cause, FeedbackSource, StoredUnit
from agent_build_kit.pipeline.units import (
    CLOSED,
    FAILED,
    HELD,
    IN_REVIEW,
    MERGED,
    PLANNED,
    RUNNING,
    SATISFIED,
    waiting_on,
)

# A label a person adds to instruct the pipeline starts with this; one the
# pipeline maintains never does.
INSTRUCTION_PREFIX = "agent-"


class StateStyle(Frozen):
    """How one state reads: its name, and the three colours the graph paints it
    with. `extra` is any further mermaid style, such as a dashed outline."""

    name: str
    fill: str
    stroke: str
    text: str
    extra: str = ""


def _style(name: str, fill: str, stroke: str, text: str, extra: str = "") -> StateStyle:
    return StateStyle(name=name, fill=fill, stroke=stroke, text=text, extra=extra)


# Keyed by the state as the graph classes it, which is wider than the unit
# store's own: the derived states are here too.
STATES: Mapping[str, StateStyle] = {
    PLANNED: _style("planned", "#eef2ff", "#6366f1", "#1e1b4b"),
    "blocked": _style("blocked", "#f5f5f4", "#a8a29e", "#44403c", "stroke-dasharray:3 3"),
    RUNNING: _style("running", "#fef3c7", "#d97706", "#451a03"),
    "reworking": _style("reworking", "#fef9c3", "#ca8a04", "#422006"),
    "rebasing": _style("rebasing", "#ccfbf1", "#0d9488", "#042f2e"),
    "paused_rework": _style(
        "paused-rework", "#ffedd5", "#ea580c", "#431407", "stroke-dasharray:3 3"
    ),
    HELD: _style("held", "#fae8ff", "#a21caf", "#4a044e"),
    IN_REVIEW: _style("in-review", "#dbeafe", "#2563eb", "#172554"),
    MERGED: _style("merged", "#dcfce7", "#16a34a", "#052e16"),
    SATISFIED: _style("satisfied", "#d1fae5", "#059669", "#022c22"),
    CLOSED: _style("closed", "#fee2e2", "#dc2626", "#450a0a"),
    FAILED: _style("failed", "#fecaca", "#b91c1c", "#450a0a", "stroke-width:3px"),
    UNPLANNED: _style("unplanned", "#f5f5f4", "#a8a29e", "#44403c"),
}

# Drawn by the graph and deliberately given no label: the host shows merged and
# closed itself, and an unplanned or satisfied unit has no pull request of its
# own to carry one.
UNLABELLED: frozenset[str] = frozenset({MERGED, CLOSED, UNPLANNED, SATISFIED})

_DESCRIPTIONS = {
    "planned": "Ready to start when a slot allows",
    "blocked": "Waiting on a unit it depends on",
    "running": "An agent is building this unit",
    "reworking": "An agent is answering review or check feedback on this unit",
    "rebasing": "An agent is moving this unit onto a changed base or resolving a conflict",
    "paused_rework": "Stopped because a unit it depends on went back for rework",
    "held": "A person has taken this over; the pipeline will not touch it",
    "in_review": "Built and waiting for human review",
    "failed": "Stopped on something it could not get past",
}


def state_label(state: str) -> Label | None:
    """The label for a state, or None where it is left unlabelled."""
    if state in UNLABELLED or state not in STATES:
        return None
    style = STATES[state]
    return Label(
        name=style.name,
        color=style.stroke.removeprefix("#"),
        description=_DESCRIPTIONS[state],
    )


def state_label_names() -> frozenset[str]:
    """Every label the pipeline maintains as a unit's state."""
    return frozenset(label.name for key in STATES if (label := state_label(key)))


def change_label(change: str) -> Label:
    """The label naming the change a pull request belongs to.

    A plain name — lowercase letters, digits and dashes, at most 50 characters —
    so every forge accepts it and can address it by name.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", change.lower()).strip("-")
    return Label(
        name=f"change-{slug}"[:50].rstrip("-"),
        color="64748b",
        description="The change this pull request belongs to",
    )


def effective_state(unit: StoredUnit, units: list[StoredUnit]) -> str:
    """The key in `STATES` a unit currently reads as.

    A planned unit the scheduler would hold back is *blocked*, not merely
    planned — that distinction is the whole point of the diagram. Asked of the
    scheduler's own rule, which this used to restate and had drifted from: it
    showed a unit as startable while its same-repo parent was still building.
    """
    if unit.state == RUNNING:
        return _running_status(unit)
    if unit.state != PLANNED:
        return unit.state

    # Stopped part-way through its loop, rather than never started: a run that
    # held at a boundary records a return to planned with a note saying why. A
    # usage pause is not one: the unit stays `running`, interrupted, in its thread.
    if waiting_on(unit, units):
        paused = unit.cause in (Cause.BASE_CHANGED, Cause.UPSTREAM_WENT_BACK)
        return "paused_rework" if paused else "blocked"
    return PLANNED


_REBASING_CAUSES = (Cause.BASE_CHANGED, Cause.RESTACK_CONFLICT, Cause.RESTACK_DEFERRED)


def _latest_cause(unit: StoredUnit) -> str | None:
    """The cause that applies to the unit's current run: the newest history entry
    carrying one, looking back through `running` entries (the graph records its
    events on them) and no further than the entry that put the unit into
    running."""
    for entry in reversed(unit.history):
        if entry.get("cause"):
            return entry["cause"]
        if entry.get("state") != RUNNING:
            return None
    return None


def _running_status(unit: StoredUnit) -> str:
    """What a running unit is doing, from why it was last sent back and the
    feedback it was given; derived, never stored."""
    cause = _latest_cause(unit)
    if unit.feedback_source is FeedbackSource.CONFLICT or cause in _REBASING_CAUSES:
        return "rebasing"
    if unit.feedback_source in (FeedbackSource.REVIEW, FeedbackSource.CI):
        return "reworking"
    return RUNNING
