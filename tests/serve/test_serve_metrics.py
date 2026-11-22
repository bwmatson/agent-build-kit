"""The metrics page's catalogue and sources (spec: web-ui)."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_store import Cause, FeedbackSource
from agent_build_kit.pipeline.units import RUNNING
from agent_build_kit.serve.metrics import catalogue
from agent_build_kit.serve.server import create_app
from agent_build_kit.settings import reload
from tests.ledger_lines import agent_line, span_line, write_ledger
from tests.metric_names import emitted_names
from tests.serving import seed_pipeline

Handler = Callable[[httpx.Request], httpx.Response]


class FakePrometheus:
    """Answers `/api/v1/query` and `/query_range` with the JSON Prometheus sends:
    one series per query, with a single sample of 42."""

    url = "http://prometheus.test"

    def __init__(self) -> None:
        self.queries: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.queries += parse_qs(request.url.query.decode()).get("query", [])
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": {
                    "resultType": "matrix",
                    "result": [
                        {
                            "metric": {"__name__": "abk", "kind": "input"},
                            "values": [[1767261600, "42"]],
                        }
                    ],
                },
            },
        )


class FakeTempo:
    """Answers `/api/search` with the JSON Tempo sends: `traceID`, root names, the
    start as a string of unix nanoseconds and the duration in milliseconds."""

    url = "http://tempo.test"

    def __init__(self) -> None:
        self.requests: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request.url.raw_path.decode())
        return httpx.Response(
            200,
            json={
                "traces": [
                    {
                        "traceID": "5b8efff798038103d269b633813fc60c",
                        "rootServiceName": "agent-build-kit",
                        "rootTraceName": "abk.tick",
                        "startTimeUnixNano": "1767261600000000000",
                        "durationMs": 1234,
                    }
                ],
                "metrics": {"inspectedBytes": "1"},
            },
        )


DEAD_URL = "http://dead.test"


def refuse_connection(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("connection refused", request=request)


@pytest.fixture
def upstreams(monkeypatch: pytest.MonkeyPatch) -> dict[str, Handler]:
    """Hosts the page may reach, each answered in-process; an unknown host is refused."""
    handlers: dict[str, Handler] = {"dead.test": refuse_connection}

    def route(request: httpx.Request) -> httpx.Response:
        handler = handlers.get(request.url.host)
        if handler is None:
            raise httpx.ConnectError("no such host", request=request)
        return handler(request)

    transport = httpx.MockTransport(route)
    monkeypatch.setattr(
        httpx.HTTPTransport,
        "handle_request",
        lambda self, request: transport.handle_request(request),
    )
    return handlers


@pytest.fixture
def tempo(upstreams: dict[str, Handler]) -> FakeTempo:
    fake = FakeTempo()
    upstreams["tempo.test"] = fake
    return fake


@pytest.fixture
def prometheus(upstreams: dict[str, Handler]) -> FakePrometheus:
    fake = FakePrometheus()
    upstreams["prometheus.test"] = fake
    return fake


def point_at(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    monkeypatch.setenv("ABK_PROMETHEUS_URL", url)
    monkeypatch.setenv("ABK_TEMPO_URL", url)
    reload(None)


@pytest.fixture(autouse=True)
def stores_unset(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv("ABK_PROMETHEUS_URL", raising=False)
    monkeypatch.delenv("ABK_TEMPO_URL", raising=False)
    reload(None)
    yield
    monkeypatch.undo()
    reload(None)


@pytest.fixture
def page(inst: Installation) -> TestClient:
    return TestClient(create_app(inst))


def test_the_catalogue_lists_every_instrument_the_package_emits() -> None:
    listed = {instrument.name for instrument in catalogue()}

    assert emitted_names()
    assert listed == emitted_names()


def test_a_new_instrument_appears_without_an_edit(tmp_path: Path) -> None:
    (tmp_path / "newmod.py").write_text(
        "from agent_build_kit import telemetry\n"
        "\n"
        "def run() -> None:\n"
        '    telemetry.count("abk.sample.things", 1, kind="x", role="y")\n'
        '    telemetry.duration("abk.sample.wait", 2.0, bucket="z")\n'
        '    telemetry.level("abk.sample.depth", 3, state="s")\n'
        '    telemetry.observe("abk.sample.size", 4.0)\n'
        '    attrs = {"repo": 1, "tier": 2}\n'
        '    telemetry.count("abk.sample.spread", 1, **attrs, kind="k")\n'
    )

    listed = {(i.name, i.type, i.attributes) for i in catalogue(tmp_path)}

    assert listed == {
        ("abk.sample.things", "counter", ("kind", "role")),
        ("abk.sample.wait", "histogram", ("bucket",)),
        ("abk.sample.depth", "gauge", ("state",)),
        ("abk.sample.size", "histogram", ()),
        ("abk.sample.spread", "counter", ("repo", "tier", "kind")),
    }


def test_the_page_serves_the_catalogue_with_a_chart_for_each_metric(
    page: TestClient, prometheus: FakePrometheus, monkeypatch: pytest.MonkeyPatch
) -> None:
    point_at(monkeypatch, prometheus.url)

    answer = page.get("/api/metrics").json()

    assert {m["name"] for m in answer["metrics"]} == emitted_names()
    assert all("series" in m and m["type"] for m in answer["metrics"])


def test_with_prometheus_answering_charts_use_windowed_sums(
    page: TestClient, prometheus: FakePrometheus, monkeypatch: pytest.MonkeyPatch
) -> None:
    point_at(monkeypatch, prometheus.url)

    answer = page.get("/api/metrics").json()

    assert answer["source"] == "prometheus"
    assert prometheus.queries
    gauges = {i.name.replace(".", "_") for i in catalogue() if i.type == "gauge"}
    delta = [q for q in prometheus.queries if not any(f"{g})" in q for g in gauges)]
    assert any("abk_units_reclaimed_total" in q for q in delta)
    assert delta
    assert all("sum_over_time(" in q for q in delta), delta
    assert not [q for q in prometheus.queries if re.search(r"\b(rate|increase)\(", q)]
    values = [p[1] for m in answer["metrics"] for s in m["series"] for p in s["points"]]
    assert 42 in values


def test_with_prometheus_down_the_same_metrics_come_from_local_records(
    upstreams: dict[str, Handler],
    inst: Installation,
    page: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    point_at(monkeypatch, DEAD_URL)
    write_ledger(
        inst.state_dir / "usage-ledger.jsonl",
        agent_line(cost_usd=1.5),
        agent_line(cost_usd=2.25, unit="add-marker/2"),
    )

    answer = page.get("/api/metrics").json()

    assert answer["source"] == "local"
    assert {m["name"] for m in answer["metrics"]} == emitted_names()
    cost = next(m for m in answer["metrics"] if m["name"] == "abk.agent.cost")
    assert sum(p[1] for s in cost["series"] for p in s["points"]) == pytest.approx(3.75)
    assert {s["labels"]["role"] for s in cost["series"]} == {"implement"}


def metric(answer: dict, name: str) -> dict:
    return next(m for m in answer["metrics"] if m["name"] == name)


def test_with_prometheus_down_durations_and_unit_counts_come_from_local_files(
    upstreams: dict[str, Handler],
    inst: Installation,
    page: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    point_at(monkeypatch, DEAD_URL)
    seed_pipeline(inst)
    write_ledger(
        inst.state_dir / "usage-ledger.jsonl",
        span_line(node="implement", duration_ms=1000),
        span_line(node="implement", duration_ms=3000),
        span_line(node="implement", command="pytest", duration_ms=9000),
        span_line(node="", waited="slot", duration_ms=4000),
    )

    answer = page.get("/api/metrics").json()

    nodes = metric(answer, "abk.node.duration")["series"]
    assert [(s["labels"], [p[1] for p in s["points"]]) for s in nodes] == [
        ({"node": "implement"}, [2.0])
    ]
    waits = metric(answer, "abk.wait.duration")["series"]
    assert [(s["labels"], [p[1] for p in s["points"]]) for s in waits] == [
        ({"bucket": "slot"}, [4.0])
    ]
    counted = {
        s["labels"]["state"]: s["points"][0][1] for s in metric(answer, "abk.units")["series"]
    }
    # One series per stored state: the blocked unit is planned, as it is stored.
    assert counted == {
        "merged": 1,
        "in_review": 1,
        "planned": 2,
        "held": 1,
        "failed": 1,
        "running": 1,
        "satisfied": 1,
        "closed": 1,
    }


def test_units_reading_reworking_or_rebasing_are_counted_as_running(
    upstreams: dict[str, Handler],
    inst: Installation,
    page: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    point_at(monkeypatch, DEAD_URL)
    store = seed_pipeline(inst)
    store.set_feedback("feature/7", "rename it", source=FeedbackSource.REVIEW)
    store.set_state("feature/7", RUNNING, note="rework requested", cause=Cause.REWORK)
    store.set_state("feature/4", RUNNING, note="base moved", cause=Cause.BASE_CHANGED)

    answer = page.get("/api/metrics").json()

    counted = {
        s["labels"]["state"]: s["points"][0][1] for s in metric(answer, "abk.units")["series"]
    }
    assert counted["running"] == 2
    assert "reworking" not in counted
    assert "rebasing" not in counted


def test_with_prometheus_down_the_ledgers_metric_records_draw_their_charts(
    upstreams: dict[str, Handler],
    inst: Installation,
    page: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    point_at(monkeypatch, DEAD_URL)
    seed_pipeline(inst)

    def record(name: str, value: float, **attributes: str) -> dict:
        return {
            "kind": "metric",
            "at": "2026-01-01T10:00:00+00:00",
            "metric": name,
            "value": value,
            "attributes": attributes,
        }

    write_ledger(
        inst.state_dir / "usage-ledger.jsonl",
        record("abk.tick.duration", 2, outcome="idle"),
        record("abk.tick.duration", 4, outcome="idle"),
        record("abk.usage.pauses", 1, kind="usage"),
        record("abk.usage.pauses", 1, kind="usage"),
    )

    answer = page.get("/api/metrics").json()

    ticks = metric(answer, "abk.tick.duration")["series"]
    assert [(s["labels"], [p[1] for p in s["points"]]) for s in ticks] == [
        ({"outcome": "idle"}, [3.0])
    ]
    pauses = metric(answer, "abk.usage.pauses")["series"]
    assert [(s["labels"], [p[1] for p in s["points"]]) for s in pauses] == [
        ({"kind": "usage"}, [2.0])
    ]


def test_a_query_prometheus_refuses_leaves_one_chart_empty_not_the_page_local(
    upstreams: dict[str, Handler], page: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refusing(request: httpx.Request) -> httpx.Response:
        query = parse_qs(request.url.query.decode())["query"][0]
        if "abk_agent_cost" in query:
            return httpx.Response(400, json={"status": "error", "error": "bad"})
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": {"result": [{"metric": {}, "values": [[1767261600, "7"]]}]},
            },
        )

    upstreams["refusing.test"] = refusing
    point_at(monkeypatch, "http://refusing.test")
    answer = page.get("/api/metrics").json()

    assert answer["source"] == "prometheus"
    assert metric(answer, "abk.agent.cost")["series"] == []
    assert metric(answer, "abk.units")["series"]


def test_the_catalogue_gives_the_ledger_metrics_all_their_attributes() -> None:
    listed = {i.name: set(i.attributes) for i in catalogue()}
    ledger = {"repo", "tier", "node", "role", "model", "source"}

    assert listed["abk.agent.cost"] == ledger
    assert listed["abk.agent.tokens"] == ledger | {"kind"}


def test_the_tokens_query_selects_one_of_the_two_series_that_write_the_counter(
    page: TestClient, prometheus: FakePrometheus, monkeypatch: pytest.MonkeyPatch
) -> None:
    point_at(monkeypatch, prometheus.url)

    page.get("/api/metrics")

    tokens = [q for q in prometheus.queries if "abk_agent_tokens" in q]
    assert tokens
    assert all(re.search(r"abk_agent_tokens_total\{[^}]*source\s*!?=", q) for q in tokens), tokens


def test_with_tempo_answering_the_page_lists_its_traces(
    page: TestClient, tempo: FakeTempo, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ABK_TEMPO_URL", tempo.url)
    reload(None)

    traces = page.get("/api/metrics").json()["traces"]

    assert traces["source"] == "tempo"
    assert traces["items"] == [
        {
            "id": "5b8efff798038103d269b633813fc60c",
            "name": "abk.tick",
            "start": "2026-01-01T10:00:00+00:00",
            "duration_ms": 1234,
        }
    ]
    asked = urlparse(tempo.requests[0])
    assert asked.path == "/api/search"
    assert parse_qs(asked.query)["tags"] == ["service.name=agent-build-kit"]


@pytest.mark.parametrize("down", [False, True])
def test_with_tempo_down_or_unset_traces_come_from_the_ledger_spans(
    upstreams: dict[str, Handler],
    inst: Installation,
    page: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    down: bool,
) -> None:
    if down:
        monkeypatch.setenv("ABK_TEMPO_URL", DEAD_URL)
        reload(None)
    write_ledger(
        inst.state_dir / "usage-ledger.jsonl",
        span_line(node="implement", started="2026-01-01T10:00:00+00:00", duration_ms=1500),
    )

    traces = page.get("/api/metrics").json()["traces"]

    assert traces["source"] == "local"
    assert [(t["name"], t["duration_ms"]) for t in traces["items"]] == [("implement", 1500)]


def test_the_dashboard_link_opens_the_pipeline_dashboard(
    page: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert page.get("/api/metrics").json()["dashboard"] is None
    monkeypatch.setenv("ABK_GRAFANA_URL", "http://grafana.example:3000/")
    reload(None)

    dashboard = page.get("/api/metrics").json()["dashboard"]

    assert dashboard == "http://grafana.example:3000/d/abk-pipeline"


def test_with_no_store_configured_the_page_says_local(page: TestClient) -> None:
    assert page.get("/api/metrics").json()["source"] == "local"
