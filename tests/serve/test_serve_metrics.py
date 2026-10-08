"""The metrics page's catalogue and sources (spec: web-ui)."""

from __future__ import annotations

import http.server
import json
import re
import socket
import threading
from collections.abc import Iterator
from importlib import resources
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from agent_build_kit.installation import Installation
from agent_build_kit.serve.metrics import catalogue
from agent_build_kit.serve.server import create_app
from agent_build_kit.settings import reload
from tests.ledger_lines import agent_line, span_line, write_ledger
from tests.serving import EXPECTED, seed_pipeline

EMIT_CALL = re.compile(
    r"telemetry\.(?:duration|observe|count|level)\(\s*[\"'](abk\.[a-z0-9_.]+)[\"']"
)


def emitted_names() -> set[str]:
    names: set[str] = set()
    stack = [resources.files("agent_build_kit")]
    while stack:
        for entry in stack.pop().iterdir():
            if entry.is_dir():
                stack.append(entry)
            elif entry.name.endswith(".py"):
                names.update(EMIT_CALL.findall(entry.read_text()))
    return names


class FakePrometheus:
    """Answers `/api/v1/query` and `/query_range` with the JSON Prometheus sends:
    one series per query, with a single sample of 42."""

    def __init__(self) -> None:
        self.queries: list[str] = []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                url = urlparse(self.path)
                outer.queries += parse_qs(url.query).get("query", [])
                body = json.dumps(
                    {
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
                    }
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                pass

        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


class FakeTempo:
    """Answers `/api/search` with the JSON Tempo sends: `traceID`, root names, the
    start as a string of unix nanoseconds and the duration in milliseconds."""

    def __init__(self) -> None:
        self.requests: list[str] = []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                outer.requests.append(self.path)
                body = json.dumps(
                    {
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
                    }
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                pass

        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture
def tempo() -> Iterator[FakeTempo]:
    fake = FakeTempo()
    yield fake
    fake.close()


def dead_url() -> str:
    with socket.socket() as closed:
        closed.bind(("127.0.0.1", 0))
        return f"http://127.0.0.1:{closed.getsockname()[1]}"


@pytest.fixture
def prometheus() -> Iterator[FakePrometheus]:
    fake = FakePrometheus()
    yield fake
    fake.close()


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
    inst: Installation, page: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    point_at(monkeypatch, dead_url())
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
    inst: Installation, page: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    point_at(monkeypatch, dead_url())
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
    expected: dict[str, float] = {}
    for state, *_ in EXPECTED.values():
        expected[state] = expected.get(state, 0) + 1
    assert counted == expected


def test_with_prometheus_down_the_ledgers_metric_records_draw_their_charts(
    inst: Installation, page: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    point_at(monkeypatch, dead_url())
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
    page: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Refusing(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            query = parse_qs(urlparse(self.path).query)["query"][0]
            refused = "abk_agent_cost" in query
            body = json.dumps(
                {"status": "error", "error": "bad"}
                if refused
                else {
                    "status": "success",
                    "data": {"result": [{"metric": {}, "values": [[1767261600, "7"]]}]},
                }
            ).encode()
            self.send_response(400 if refused else 200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Refusing)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        point_at(monkeypatch, f"http://127.0.0.1:{server.server_address[1]}")
        answer = page.get("/api/metrics").json()
    finally:
        server.shutdown()
        server.server_close()

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
    inst: Installation, page: TestClient, monkeypatch: pytest.MonkeyPatch, down: bool
) -> None:
    if down:
        monkeypatch.setenv("ABK_TEMPO_URL", dead_url())
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
