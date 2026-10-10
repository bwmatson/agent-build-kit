"""Lines of the usage ledger as the capture and span code write them, for the
report's tests: the ledger is the report's only input, so fixtures are its lines."""

from __future__ import annotations

import json
from pathlib import Path


def _flat_line(**fields) -> dict:
    """An agent line as it was written before the `cost` object: one flat figure."""
    return {
        "kind": "agent",
        "at": "2026-01-01T10:00:00+00:00",
        "unit": "add-marker/1",
        "change": "add-marker",
        "repo": "app",
        "tier": "tier1",
        "node": "implement",
        "round": 0,
        "role": "implement",
        "model": "model-a",
        "runtime": "claude_code",
        "session_id": "sess-1",
        "input_tokens": 100,
        "output_tokens": 50,
        "cache_read_input_tokens": 1000,
        "cache_creation_input_tokens": 200,
        "cost_usd": 1.0,
        "turns": 3,
        "duration_ms": 60000,
        "usage_source": "reported",
        "outcome": "ok",
        **fields,
    }


def agent_line(**fields) -> dict:
    """An agent line as it is written now; `cost_usd` and `reported_cost_usd` name the call's
    own spend and the runtime's own figure, which the line carries in its `cost` object."""
    line = _flat_line(**fields)
    spend = line.pop("cost_usd", None)
    reported = line.pop("reported_cost_usd", None)
    if "cost" in line or (spend is None and reported is None):
        return line
    cost = {"incremental_usd": spend, "basis": "reported", "reported_usd": reported}
    return line | {"cost": cost}


def costed_line(
    incremental: float | None,
    cumulative: float | None = None,
    *,
    basis: str = "derived",
    **fields,
) -> dict:
    """An agent line as it is written now: the `cost` object and no flat figure."""
    line = _flat_line(**fields)
    del line["cost_usd"]
    return line | {
        "cost": {"incremental_usd": incremental, "cumulative_usd": cumulative, "basis": basis}
    }


def legacy_line(cost_usd: float, **fields) -> dict:
    """An agent line as it was written before the `cost` object: one flat figure."""
    return _flat_line(cost_usd=cost_usd, **fields)


# The session of nine calls whose recorded totals summed to 147.80 and whose own spends
# summed to its final cumulative: (node, round, own spend, running total).
WORKED_SESSION = [
    ("tests", 0, 2.63, 2.63),
    ("implement", 0, 2.86, 5.49),
    ("rework", 1, 7.69, 13.18),
    ("rework", 2, 2.22, 15.40),
    ("rework", 0, 4.38, 19.77),
    ("fix_checks", 1, 0.84, 20.62),
    ("rework", 1, 0.78, 21.40),
    ("rework", 0, 2.52, 23.92),
    ("rework", 1, 1.47, 25.39),
]


def worked_session(**fields) -> list[dict]:
    """The worked session as ledger lines, in time order, each call after the first resumed."""
    return [
        costed_line(
            own,
            total,
            basis="first" if n == 0 else "derived",
            at=f"2026-01-01T10:{n:02d}:00+00:00",
            node=node,
            round=round_number,
            resumed=n > 0,
            session_id="sess-worked",
            **fields,
        )
        for n, (node, round_number, own, total) in enumerate(WORKED_SESSION)
    ]


def span_line(**fields) -> dict:
    return {
        "kind": "span",
        "at": "2026-01-01T10:05:00+00:00",
        "unit": "add-marker/1",
        "change": "add-marker",
        "node": "implement",
        "round": 0,
        "started": "2026-01-01T10:00:00+00:00",
        "ended": "2026-01-01T10:05:00+00:00",
        "duration_ms": 1000,
        "outcome": "ok",
        "waited": "",
        "command": "",
        **fields,
    }


def write_ledger(path: Path, *lines: dict | str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join((x if isinstance(x, str) else json.dumps(x)) + "\n" for x in lines))
    return path


def fixture_ledger(path: Path) -> Path:
    """Four calls over three days, two changes, two repos, two models."""
    return write_ledger(
        path,
        agent_line(),
        agent_line(
            at="2026-01-02T09:00:00+00:00",
            node="review",
            round=1,
            role="review",
            model="model-b",
            session_id="sess-2",
            input_tokens=10,
            output_tokens=5,
            cache_read_input_tokens=100,
            cache_creation_input_tokens=20,
            cost_usd=0.25,
            duration_ms=30000,
        ),
        agent_line(
            at="2026-01-02T11:00:00+00:00",
            unit="add-marker/2",
            repo="platform",
            session_id="sess-3",
            input_tokens=30,
            output_tokens=20,
            cache_read_input_tokens=300,
            cache_creation_input_tokens=60,
            cost_usd=0.5,
            duration_ms=45000,
        ),
        agent_line(
            at="2026-01-03T08:00:00+00:00",
            unit="feature/1",
            change="feature",
            session_id="sess-4",
            input_tokens=7,
            output_tokens=3,
            cache_read_input_tokens=70,
            cache_creation_input_tokens=14,
            cost_usd=0.125,
            duration_ms=15000,
            usage_source="gateway",
        ),
    )
