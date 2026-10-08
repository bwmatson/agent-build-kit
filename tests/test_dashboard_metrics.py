"""The dashboard's queries use the metric names the framework emits, so a
rename on either side fails here (spec: telemetry)."""

from __future__ import annotations

import json
import re
from importlib import resources
from typing import Any

# Prometheus exposes an OTLP metric as its name with dots as underscores, the
# unit appended for a histogram in seconds, and a type suffix on top.
EXPOSITION_SUFFIXES = ("_bucket", "_sum", "_count", "_total", "_seconds")
EMIT_CALL = re.compile(
    r"telemetry\.(?:duration|observe|count|level)\(\s*[\"'](abk\.[a-z0-9_.]+)[\"']"
)
QUERIED = re.compile(r"\babk_[a-z0-9_]+")


def _dashboard() -> dict[str, Any]:
    path = resources.files("agent_build_kit") / "telemetry" / "dashboards" / "pipeline.json"
    return json.loads(path.read_text())


def _expressions(node: Any) -> list[str]:
    """Every query expression in the dashboard, wherever the panel nests it."""
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ("expr", "expression") and isinstance(value, str):
                found.append(value)
            else:
                found += _expressions(value)
    elif isinstance(node, list):
        for item in node:
            found += _expressions(item)
    return found


def _emitted() -> set[str]:
    names: set[str] = set()
    stack = [resources.files("agent_build_kit")]
    while stack:
        for entry in stack.pop().iterdir():
            if entry.is_dir():
                stack.append(entry)
            elif entry.name.endswith(".py"):
                names.update(EMIT_CALL.findall(entry.read_text()))
    return names


def _base(queried: str) -> str:
    stripped = True
    while stripped:
        stripped = False
        for suffix in EXPOSITION_SUFFIXES:
            if queried.endswith(suffix):
                queried = queried[: -len(suffix)]
                stripped = True
    return queried


def test_the_dashboard_has_panels_that_query() -> None:
    dashboard = _dashboard()
    assert dashboard["panels"]
    assert _expressions(dashboard)


def test_every_metric_the_dashboard_queries_is_one_the_framework_emits() -> None:
    emitted = {name.replace(".", "_") for name in _emitted()}
    assert emitted, "found no emitted metric names to compare with"

    queried = {
        _base(name)
        for expression in _expressions(_dashboard())
        for name in QUERIED.findall(expression)
    }

    assert queried, "the dashboard queries no abk_ metric"
    assert queried <= emitted, sorted(queried - emitted)


def test_the_dashboard_shows_the_ledger_cost_tokens_node_and_wait_durations() -> None:
    queried = {
        _base(name)
        for expression in _expressions(_dashboard())
        for name in QUERIED.findall(expression)
    }

    assert {
        "abk_agent_cost",
        "abk_agent_tokens",
        "abk_node_duration",
        "abk_wait_duration",
    } <= queried


def test_delta_data_is_queried_with_windowed_sums_not_rates() -> None:
    """The exporter sends delta temporality, so `rate` and `increase` over a
    window of samples undercount; every query but the gauge sums over the window."""
    delta = [
        expression
        for expression in _expressions(_dashboard())
        if QUERIED.search(expression)
        and not re.fullmatch(r"sum by \(\w+\) \(abk_units\)", expression)
    ]

    assert delta
    assert not [e for e in delta if re.search(r"\b(rate|increase)\(", e)], delta
    assert not [e for e in delta if "sum_over_time(" not in e], delta


def test_no_dashboard_query_sums_both_series_of_the_token_counter() -> None:
    """The runtime and the ledger both write `abk_agent_tokens_total`, the ledger
    with a `source`; a query must pick one or it counts every call twice."""
    selecting = re.compile(r"abk_agent_tokens_total\{[^}]*source\s*!?=")
    grouped = re.compile(r"by\s*\([^)]*\bsource\b[^)]*\)")
    unselected = [
        expression
        for expression in _expressions(_dashboard())
        if "abk_agent_tokens" in expression
        and not (selecting.search(expression) or grouped.search(expression))
    ]

    assert not unselected, unselected
