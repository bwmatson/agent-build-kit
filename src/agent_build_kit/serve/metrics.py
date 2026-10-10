"""The metrics page's catalogue and its sources (spec: web-ui).

The catalogue is read from the code: every `telemetry.count/duration/observe/level`
call with a literal `abk.` name is an instrument, so a new one appears without an
edit here. The page draws its charts from Prometheus and its recent traces from
Tempo when they answer, otherwise from the local files the pipeline keeps.
"""

from __future__ import annotations

import ast
import json
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from functools import cache
from importlib import resources
from pathlib import Path
from typing import Any, Protocol

import httpx
from pydantic import ValidationError

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.metric_records import MetricRecord
from agent_build_kit.pipeline.spans import Span
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.usage_calls import CALLS_NAME, derive_rate, read_calls
from agent_build_kit.pipeline.usage_ledger import UsageRecord, read_lines, records_in

# What each telemetry function creates; `value` and `seconds` are its own parameters.
TYPES = {"count": "counter", "duration": "histogram", "observe": "histogram", "level": "gauge"}
NOT_ATTRIBUTES = {"value", "seconds"}
WINDOW = timedelta(hours=24)
STEP_SECONDS = 3600
QUERY_TIMEOUT = 3.0
TRACE_LIMIT = 20
# The runtime and the usage ledger both write the token counter, and only the
# ledger's series carry a `source`; a query that selects neither sums every call twice.
SELECTORS = {"abk.agent.tokens": '{source!=""}'}


class Instrument(Frozen):
    """One metric the code emits: its name, its type and the attributes it carries."""

    name: str
    type: str  # "counter", "histogram" or "gauge"
    attributes: tuple[str, ...]
    unit: str = ""  # "s" for a duration histogram


class Series(Frozen):
    labels: dict[str, str]
    points: tuple[tuple[float, float], ...]


class Trace(Frozen):
    """One recent trace: its id (empty when only a ledger line records it), root
    name, start (ISO, UTC) and duration."""

    id: str
    name: str
    start: str
    duration_ms: int


class SourceDown(Exception):
    """The source could not answer."""


class MetricSource(Protocol):
    """Where the charts' figures come from; raises `SourceDown` when it cannot answer."""

    name: str

    def series(self, instrument: Instrument) -> list[Series]: ...


def dashboard_uid() -> str:
    """The uid of the dashboard `abk telemetry push-dashboard` pushes."""
    path = resources.files("agent_build_kit") / "telemetry" / "dashboards" / "pipeline.json"
    return str(json.loads(path.read_text())["uid"])


def _dict_keys(scope: ast.AST) -> dict[str, list[str]]:
    """The keys of every `name = {"key": ...}` assigned within `scope`."""
    keys: dict[str, list[str]] = {}
    for node in ast.walk(scope):
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        if not isinstance(value, ast.Dict):
            continue
        literal = [str(k.value) for k in value.keys if isinstance(k, ast.Constant)]
        for target in targets:
            if isinstance(target, ast.Name):
                keys[target.id] = literal
    return keys


def _attribute_names(call: ast.Call, dicts: dict[str, list[str]]) -> list[str]:
    """The attributes a telemetry call passes: its keywords, and the keys of a
    `**name` that is a dict literal assigned in the same scope."""
    names: list[str] = []
    for keyword in call.keywords:
        if keyword.arg:
            names.append(keyword.arg)
        elif isinstance(keyword.value, ast.Name):
            names += dicts.get(keyword.value.id, [])
    return [n for n in names if n not in NOT_ATTRIBUTES]


def _calls_with_scope(tree: ast.Module) -> list[tuple[ast.Call, dict[str, list[str]]]]:
    scopes: list[ast.AST] = [tree]
    scopes += [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)]
    found = []
    for scope in scopes:
        dicts = _dict_keys(scope)
        found += [(n, dicts) for n in ast.walk(scope) if isinstance(n, ast.Call)]
    return found


def catalogue(root: Path | None = None) -> list[Instrument]:
    """Every instrument the telemetry calls under `root` (the package by default) define."""
    if root is None:
        return list(_package_catalogue())
    return _read_catalogue(root)


@cache
def _package_catalogue() -> tuple[Instrument, ...]:
    # The code cannot change while the server runs.
    return tuple(_read_catalogue(Path(__file__).resolve().parent.parent))


def _read_catalogue(root: Path) -> list[Instrument]:
    found: dict[str, Instrument] = {}
    for path in sorted(root.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text())
        except (OSError, SyntaxError, ValueError):
            continue
        for node, dicts in _calls_with_scope(tree):
            if not (
                isinstance(node.func, ast.Attribute)
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
            known = found.get(name)
            attributes = list(known.attributes) if known else []
            attributes += [a for a in _attribute_names(node, dicts) if a not in attributes]
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
    selector = SELECTORS.get(instrument.name, "")
    window = f"{STEP_SECONDS}s"
    if instrument.type == "gauge":
        return f"{by} ({base}{selector})"
    if instrument.type == "counter":
        return f"{by} (sum_over_time({base}_total{selector}[{window}]))"
    return (
        f"{by} (sum_over_time({base}_sum{selector}[{window}])) / "
        f"{by} (sum_over_time({base}_count{selector}[{window}]))"
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
        except httpx.TransportError as error:
            raise SourceDown(str(error)) from error
        if response.status_code >= 500:
            raise SourceDown(f"prometheus answered {response.status_code}")
        # A query it refuses (4xx, or `status: error`) leaves that one chart empty.
        try:
            return [
                Series(
                    labels={k: str(v) for k, v in item["metric"].items() if k != "__name__"},
                    points=tuple((float(t), float(v)) for t, v in item["values"]),
                )
                for item in response.json()["data"]["result"]
            ]
        except (ValueError, KeyError, TypeError):
            return []


def tempo_traces(
    url: str,
    service: str,
    *,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> list[Trace]:
    """The pipeline's recent traces from Tempo's search; raises `SourceDown`."""
    end = now()
    try:
        response = httpx.get(
            f"{url.rstrip('/')}/api/search",
            params={
                "tags": f"service.name={service}",
                "start": int((end - WINDOW).timestamp()),
                "end": int(end.timestamp()),
                "limit": TRACE_LIMIT,
            },
            timeout=QUERY_TIMEOUT,
        )
        response.raise_for_status()
        found = response.json()["traces"]
        return [
            Trace(
                id=str(item["traceID"]),
                name=str(item.get("rootTraceName") or item.get("rootServiceName") or ""),
                start=datetime.fromtimestamp(int(item["startTimeUnixNano"]) / 1e9, UTC).isoformat(),
                duration_ms=int(item.get("durationMs", 0)),
            )
            for item in found
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
    "abk.agent.cost": lambda r: [({}, r.cost.incremental_usd if r.cost else None)],
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


def _span_measure(name: str, span: Span) -> dict[str, str] | None:
    """The labels a span's time is charted under for one duration metric, or None
    when it is not part of it; mirrors `spans.export_span`."""
    if name == "abk.wait.duration":
        return {"bucket": span.waited} if span.waited else None
    if name == "abk.node.duration":
        return {"node": span.node} if not span.waited and not span.command else None
    return None


def _spans_in(lines: list[str]) -> list[Span]:
    spans = []
    for line in lines:
        try:
            raw = json.loads(line)
            if raw.get("kind") == "span":
                spans.append(Span.model_validate(raw))
        except (ValueError, AttributeError, ValidationError):
            continue
    return spans


def _metric_records_in(lines: list[str]) -> list[MetricRecord]:
    found = []
    for line in lines:
        try:
            raw = json.loads(line)
            if raw.get("kind") == "metric":
                found.append(MetricRecord.model_validate(raw))
        except (ValueError, AttributeError, ValidationError):
            continue
    return found


def local_traces(spans: list[Span]) -> list[Trace]:
    """The most recent stretches of work the ledger's span lines record."""
    work = sorted((s for s in spans if not s.command), key=lambda s: s.started, reverse=True)
    return [
        Trace(id="", name=s.node or s.waited, start=s.started, duration_ms=s.duration_ms)
        for s in work[:TRACE_LIMIT]
    ]


class LocalSource:
    """The figures the pipeline's own files hold: the usage ledger gives cost,
    tokens and turns by day, its span lines the node and wait durations, its
    `metric` lines the figures the pipeline records about itself (tick and unit
    durations, review rounds, check failures, usage pauses), and the unit store the count of
    units in each state."""

    name = "local"

    def __init__(
        self,
        ledger: Path,
        units: list[StoredUnit] | None = None,
        *,
        calls: Path | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        lines = read_lines(ledger)
        self._calls = [r for r in records_in(lines) if r.usage_source != "none"]
        self.spans = _spans_in(lines)
        self._metrics = _metric_records_in(lines)
        self._units = units or []
        self._now = now
        self._usage_calls = read_calls(calls) if calls is not None else []

    def _call_samples(self, instrument: Instrument) -> list[tuple[str, dict[str, str], float]]:
        """The usage endpoint's call record: one count per call, and the safe interval now."""
        if instrument.name == "abk.usage.calls":
            return [
                (c.at.isoformat(), {"outcome": c.outcome, "caller": c.caller}, 1.0)
                for c in self._usage_calls
            ]
        if instrument.name == "abk.usage.safe_interval" and self._usage_calls:
            now = self._now()
            interval = derive_rate(self._usage_calls, now=now).safe_interval_seconds
            return [] if interval is None else [(now.isoformat(), {}, float(interval))]
        return []

    def _samples(self, instrument: Instrument) -> list[tuple[str, dict[str, str], float]]:
        """(when, labels, value) for every local record that counts in the metric."""
        samples: list[tuple[str, dict[str, str], float]] = []
        measure = MEASURES.get(instrument.name)
        if measure is not None:
            for record in self._calls:
                for extra, value in measure(record):
                    if value is None:
                        continue
                    labels = {a: LABELS[a](record) for a in instrument.attributes if a in LABELS}
                    samples.append((record.at, {**labels, **extra}, float(value)))
        samples += self._call_samples(instrument)
        for span in self.spans:
            labels = _span_measure(instrument.name, span)
            if labels is not None:
                samples.append((span.at, labels, span.duration_ms / 1000))
        for record in self._metrics:
            if record.metric == instrument.name:
                labels = {
                    a: str(record.attributes[a])
                    for a in instrument.attributes
                    if a in record.attributes
                }
                samples.append((record.at, labels, record.value))
        return samples

    def _unit_series(self) -> list[Series]:
        counts: dict[str, int] = defaultdict(int)
        for unit in self._units:
            counts[unit.state] += 1
        at = self._now().timestamp()
        return [
            Series(labels={"state": s}, points=((at, float(n)),)) for s, n in sorted(counts.items())
        ]

    def series(self, instrument: Instrument) -> list[Series]:
        if instrument.name == "abk.units":
            return self._unit_series()
        grouped: dict[tuple[tuple[str, str], ...], dict[float, list[float]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for at, labels, value in self._samples(instrument):
            try:
                day = datetime.fromisoformat(at).astimezone(UTC)
            except ValueError:
                continue
            midnight = day.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
            grouped[tuple(sorted(labels.items()))][midnight].append(value)
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


def metrics_page(
    prometheus_url: str,
    tempo_url: str,
    ledger: Path,
    units: list[StoredUnit],
    dashboard: str | None,
    service: str,
) -> dict[str, Any]:
    """The catalogue with a chart's series for each metric, which source drew them,
    and the recent traces with the source that listed them."""
    instruments = catalogue()
    local = LocalSource(ledger, units, calls=ledger.parent / CALLS_NAME)
    source: MetricSource = PrometheusSource(prometheus_url) if prometheus_url else local
    try:
        drawn = {i.name: source.series(i) for i in instruments}
    except SourceDown:
        source = local
        drawn = {i.name: source.series(i) for i in instruments}
    traces, traces_from = local_traces(local.spans), "local"
    if tempo_url:
        try:
            traces, traces_from = tempo_traces(tempo_url, service), "tempo"
        except SourceDown:
            pass
    return {
        "source": source.name,
        "dashboard": dashboard,
        "traces": {"source": traces_from, "items": [t.model_dump() for t in traces]},
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
