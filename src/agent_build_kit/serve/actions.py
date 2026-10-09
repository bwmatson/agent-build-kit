"""Unit actions from the UI: requeue, hold, release and approve.

Each calls the code the CLI and the pull request poller use, through the real unit
store (its lock and write hooks), logs the UI as the actor, and refuses with the same
reason the CLI gives. Requeue is `abk requeue`'s own function; hold and release are
the poller's own dispatch of a `hold` and a `release`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from agent_build_kit.cli.pipeline import (
    deliver_hold_event,
    hold_label_on,
    log,
    requeue,
    requeue_refusal,
    store_for,
)
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.pr_poller import HOLD_LABEL
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import HELD, IN_REVIEW

ACTIONS = ("requeue", "hold", "release", "approve")
ACTOR = "the web UI"


class ActionBody(BaseModel):
    mode: Literal["resume", "rework", "restart"] = "resume"


def refusal(action: str, unit: StoredUnit, installation: Installation) -> str | None:
    """Why `action` does not apply to `unit` as stored; None when it does."""
    if action == "requeue":
        return requeue_refusal(unit)
    if action == "hold":
        if unit.state == IN_REVIEW and unit.pr is not None:
            return None
        return f"{unit.id} is {unit.state}; only an in-review unit with a pull request can be held"
    if action == "release":
        if unit.state != HELD or not unit.held_by_the_label:
            return f"{unit.id} is {unit.state}, not held by the hold label; nothing to release"
        if hold_label_on(installation, unit):
            return (
                f"{unit.id}'s pull request still carries the {HOLD_LABEL} label; "
                "remove the label on the host to release it"
            )
        return None
    return f"{unit.id}: abk has no approve command; approve its pull request on the host"


def register(
    app: FastAPI,
    installation: Installation,
    find: Callable[[str, str], tuple[StoredUnit, list[StoredUnit]]],
) -> None:
    @app.post("/api/units/{change}/{number}/actions/{action}")
    def act(
        change: str, number: str, action: str, body: ActionBody | None = None
    ) -> dict[str, Any]:
        if action not in ACTIONS:
            raise HTTPException(status_code=404, detail=f"no action {action!r}")
        unit, _ = find(change, number)
        if (reason := refusal(action, unit, installation)) is not None:
            raise HTTPException(status_code=409, detail=reason)
        log(f"{action} {unit.id}: chosen by {ACTOR}")
        store = store_for(installation)
        lines: list[str] = []
        if action == "requeue":
            code = requeue(
                installation,
                unit.id,
                (body or ActionBody()).mode,
                say=lambda text, error=False: lines.append(text),
            )
            if code:
                raise HTTPException(status_code=409, detail="\n".join(lines))
            return {"message": "\n".join(lines)}
        done = deliver_hold_event(installation, store, action, unit, say=lines.append)
        if not done:
            raise HTTPException(status_code=409, detail="\n".join(lines))
        if action == "hold":
            lines.append(f"the {HOLD_LABEL} label was not set on the host; set it there too")
        return {"message": "\n".join(lines)}


def available(unit: StoredUnit, installation: Installation) -> list[dict[str, Any]]:
    """Each action with whether it applies to `unit` and, if not, why."""
    reasons = {name: refusal(name, unit, installation) for name in ACTIONS}
    return [
        {"name": name, "enabled": reason is None, "reason": reason or ""}
        for name, reason in reasons.items()
    ]
