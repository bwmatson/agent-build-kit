"""The metrics page's catalogue and its two sources (spec: web-ui).

The catalogue is read from the code: every `telemetry.count/duration/observe/level`
call with a literal `abk.` name is an instrument, so a new one appears without an
edit here. The page draws its charts from Prometheus when it answers, otherwise
from the local files the pipeline keeps.
"""

from __future__ import annotations

import ast
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

import httpx

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.usage_ledger import UsageRecord, read_ledger

# What each telemetry function creates; `value` and `seconds` are its own parameters.
TYPES = {"count": "counter", "duration": "histogram", "observe": "histogram", "level": "gauge"}
NOT_ATTRIBUTES = {"value", "seconds"}
WINDOW = timedelta(hours=24)
STEP_SECONDS = 3600
QUERY_TIMEOUT = 3.0


class Instrument(Frozen):
    """One metric the code emits: its name, its type and the attributes it carries."""

    name: str
    type: str  # "counter", "histogram" or "gauge"
    attributes: tuple[str, ...]
    unit: str = ""  # "s" for a duration histogram


class Series(Frozen):
    labels: dict[str, str]
    points: tuple[tuple[float, float], ...]


class SourceDown(Exception):
    """The source could not answer."""


class MetricSource(Protocol):
    """Where the charts' figures come from; raises `SourceDown` when it cannot answer."""

    name: str

    def series(self, instrument: Instrument) -> list[Series]: ...


def catalogue(root: Path | None = None) -> list[Instrument]:
    """Every instrument the telemetry calls under `root` (the package by default) define."""
    root = root or Path(__file__).resolve().parent.parent
    found: dict[str, Instrument] = {}
    for path in sorted(root.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text())
        except (OSError, SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "telemetry"
                and node.func.attr in TYPES
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
                and node.args[0].value.startswith("abk.")
            ):
                continue
            name = node.args[0].value
            names = [k.arg for k in node.keywords if k.arg and k.arg not in NOT_ATTRIBUTES]
            known = found.get(name)
            attributes = list(known.attributes) if known else []
            attributes += [a for a in names if a not in attributes]
            found[name] = Instrument(
                name=name,
                type=TYPES[node.func.attr],
                attributes=tuple(attributes),
                unit="s" if node.func.attr == "duration" else "",
            )
    return sorted(found.values(), key=lambda i: i.name)


def query_for(instrument: Instrument) -> str:
    """The query for one instrument. The exporter sends delta temporality, so a
    chart sums the samples in each step instead of taking a rate."""
    by = "sum by (" + ", ".join(instrument.attributes) + ")" if instrument.attributes else "sum"
    base = instrument.name.replace(".", "_") + ("_seconds" if instrument.unit == "s" else "")
    window = f"{STEP_SECONDS}s"
    if instrument.type == "gauge":
        return f"{by} ({base})"
    if instrument.type == "counter":
        return f"{by} (sum_over_time({base}_total[{window}]))"
    return (
        f"{by} (sum_over_time({base}_sum[{window}])) / {by} (sum_over_time({base}_count[{window}]))"
    )


class PrometheusSource:
    name = "prometheus"

    def __init__(self, url: str, *, now: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self._url = url.rstrip("/")
        self._now = now

    def series(self, instrument: Instrument) -> list[Series]:
        end = self._now()
        try:
            response = httpx.get(
                f"{self._url}/api/v1/query_range",
                params={
                    "query": query_for(instrument),
                    "start": (end - WINDOW).timestamp(),
                    "end": end.timestamp(),
                    "step": STEP_SECONDS,
                },
                timeout=QUERY_TIMEOUT,
            )
            response.raise_for_status()
            return [
                Series(
                    labels={k: str(v) for k, v in item["metric"].items() if k != "__name__"},
                    points=tuple((float(t), float(v)) for t, v in item["values"]),
                )
                for item in response.json()["data"]["result"]
            ]
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
            raise SourceDown(str(error)) from error


def _token_kinds(r: UsageRecord) -> list[tuple[dict[str, str], float | None]]:
    return [
        ({"kind": "input"}, r.input_tokens),
        ({"kind": "output"}, r.output_tokens),
        ({"kind": "cache_read"}, r.cache_read_input_tokens),
        ({"kind": "cache_creation"}, r.cache_creation_input_tokens),
    ]


MEASURES: dict[str, Callable[[UsageRecord], list[tuple[dict[str, str], float | None]]]] = {
    "abk.agent.cost": lambda r: [({}, r.cost_usd)],
    "abk.agent.turns": lambda r: [({}, r.turns)],
    "abk.agent.tokens": _token_kinds,
}

LABELS: dict[str, Callable[[UsageRecord], str]] = {
    "repo": lambda r: r.repo,
    "tier": lambda r: r.tier,
    "node": lambda r: r.node,
    "role": lambda r: r.role,
    "model": lambda r: r.model or "default",
    "source": lambda r: "estimated" if r.usage_source == "estimated" else "measured",
}


class LocalSource:
    """The figures the pipeline's own files hold: the usage ledger gives cost,
    tokens and turns by day. The rest have no local record here and chart empty."""

    name = "local"

    def __init__(self, ledger: Path) -> None:
        self._calls = [r for r in read_ledger(ledger) if r.usage_source != "none"]

    def series(self, instrument: Instrument) -> list[Series]:
        measure = MEASURES.get(instrument.name)
        if measure is None:
            return []
        grouped: dict[tuple[tuple[str, str], ...], dict[float, list[float]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for record in self._calls:
            try:
                day = datetime.fromisoformat(record.at).astimezone(UTC)
            except ValueError:
                continue
            midnight = day.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
            for extra, value in measure(record):
                if value is None:
                    continue
                labels = {a: LABELS[a](record) for a in instrument.attributes if a in LABELS}
                labels.update(extra)
                grouped[tuple(sorted(labels.items()))][midnight].append(float(value))
        mean = instrument.type == "histogram"
        return [
            Series(
                labels=dict(key),
                points=tuple(
                    (day, sum(values) / len(values) if mean else sum(values))
                    for day, values in sorted(days.items())
                ),
            )
            for key, days in sorted(grouped.items())
        ]


def metrics_page(prometheus_url: str, ledger: Path, dashboard: str | None) -> dict[str, Any]:
    """The catalogue with a chart's series for each metric, and which source drew them."""
    instruments = catalogue()
    local = LocalSource(ledger)
    source: MetricSource = PrometheusSource(prometheus_url) if prometheus_url else local
    try:
        drawn = {i.name: source.series(i) for i in instruments}
    except SourceDown:
        source = local
        drawn = {i.name: source.series(i) for i in instruments}
    return {
        "source": source.name,
        "dashboard": dashboard,
        "metrics": [
            {
                "name": i.name,
                "type": i.type,
                "attributes": list(i.attributes),
                "series": [
                    {"labels": s.labels, "points": [list(p) for p in s.points]}
                    for s in drawn[i.name]
                ],
            }
            for i in instruments
        ],
    }
