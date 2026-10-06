"""Lines of the usage ledger as the capture and span code write them, for the
report's tests: the ledger is the report's only input, so fixtures are its lines."""

from __future__ import annotations

import json
from pathlib import Path


def agent_line(**fields) -> dict:
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
