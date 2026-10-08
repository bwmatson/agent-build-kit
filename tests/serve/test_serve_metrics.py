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
from tests.ledger_lines import agent_line, write_ledger

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
    )

    listed = {(i.name, i.type, i.attributes) for i in catalogue(tmp_path)}

    assert listed == {
        ("abk.sample.things", "counter", ("kind", "role")),
        ("abk.sample.wait", "histogram", ("bucket",)),
        ("abk.sample.depth", "gauge", ("state",)),
        ("abk.sample.size", "histogram", ()),
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
    delta = [q for q in prometheus.queries if "abk_units" not in q]
    assert delta
    assert all("sum_over_time(" in q for q in delta), delta
    assert not [q for q in prometheus.queries if re.search(r"\b(rate|increase)\(", q)]
    values = [p[1] for m in answer["metrics"] for s in m["series"] for p in s["points"]]
    assert 42 in values


def test_with_prometheus_down_the_same_metrics_come_from_local_records(
    inst: Installation, page: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    with socket.socket() as closed:
        closed.bind(("127.0.0.1", 0))
        dead = f"http://127.0.0.1:{closed.getsockname()[1]}"
    point_at(monkeypatch, dead)
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


def test_with_no_store_configured_the_page_says_local(page: TestClient) -> None:
    assert page.get("/api/metrics").json()["source"] == "local"
