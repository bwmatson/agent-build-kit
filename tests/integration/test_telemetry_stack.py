"""A tick's telemetry arriving in the shared stack's trace and metrics stores.

`abk tick` is the real CLI run as a process against a scratch planning repo and
a scratch code repo with a bare remote, with a real agent on this host
(the host's own Claude login) and telemetry switched on through the settings a
person would set. Only GitHub is faked: a fake server speaking the REST API,
reached through `ABK_GITHUB_API_URL`, with `gh auth token` the one command left as
a script.

The sink is one of two telemetry values. `otel` is the stack's own stores, read back through the
queries a person would use: the trace store's search API by unit id, and the metrics store's
query API by metric name. `local` is a file written by a receiver on a free port, decoded from
the OTLP/HTTP requests the tick sent. For `otel` the dev instance must be up; its published
ports are named by:

- `ABK_ACCEPTANCE_TRACES_ENDPOINT`   the trace intake, a full OTLP/HTTP URL
- `ABK_ACCEPTANCE_METRICS_ENDPOINT`  the metrics intake, a full OTLP/HTTP URL
- `ABK_ACCEPTANCE_TRACES_URL`        the trace store's base URL (search API)
- `ABK_ACCEPTANCE_METRICS_URL`       the metrics store's base URL (query API)

The fixture unit is built once per runtime and telemetry value, each parameter carrying its
values' tags.

Every run is told apart in the sink by a service name of its own, so a sink
that already holds earlier runs does not answer for this one.

Needs the dev stack, the host's Claude Code login, node for the OpenSpec CLI
and uv. Bills on demand and takes minutes, so it is marked e2e-test and excluded
from the default suite.
"""

from __future__ import annotations

import base64
import json
import shutil
import socket
import subprocess
import time
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from pydantic import Field

from agent_build_kit import config
from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from tests.factories import git, init_repo, scratch_app
from tests.forges.github_server import FakeGitHub
from tests.forges.process_host import process_env
from tests.runtime_scratch import (
    RUNTIME_PARAMS,
    TELEMETRY_PARAMS,
    TelemetryScratch,
    runtime_scratch,
    telemetry_scratch,
)
from tests.scratch_tick import TickResult, commits_on_unit_branch, register_scratch, run_tick

pytestmark = [
    pytest.mark.local_stack,
    pytest.mark.skipif(shutil.which("npx") is None, reason="npx is not on PATH"),
    pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not on PATH"),
]

CHANGE = "add-marker"
BRANCH = f"spec/{CHANGE}/1"
UNIT_ID = f"{CHANGE}/1"

# How long the stores get to make a pushed trace or series searchable.
INGEST_WAIT = 90.0
# How long a store that should hold nothing is given to prove it.
QUIET_WAIT = 20.0

TASKS = """# Tasks

## 1. [app] [unit-test] Add the marker

- [ ] 1.1 Test: `marker()` in `src/app/marker.py` returns the string `"marked"`.
- [ ] 1.2 Add `marker()` to `src/app/marker.py`.

Acceptance: none — a single function whose own test is its proof
"""


class Scratch(Frozen):
    model_config = {"arbitrary_types_allowed": True}

    planning: Path
    remote: Path
    state: Path
    env: dict[str, str] = Field(repr=False)
    host: FakeGitHub


class Built(Frozen):
    """The scratch a tick built the fixture unit in, the tick, and the service name it reported
    its telemetry under."""

    scratch: Scratch
    tick: TickResult
    service: str
    sink: TelemetryScratch


def closed_endpoint() -> str:
    """A URL on a port nothing listens on."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    return f"http://127.0.0.1:{port}"


def build_unit(
    tmp_path: Path,
    runtime: str,
    tmp_path_factory: pytest.TempPathFactory,
    sink: TelemetryScratch,
    *,
    traces: str,
    metrics: str,
    service: str | None = None,
) -> Built:
    """Build the fixture unit in one tick on `runtime` with telemetry on, pointed at
    `traces` and `metrics` (the `sink`'s intake, or a dead one), under a service name of its own."""
    scratch = runtime_scratch(runtime, tmp_path_factory, lambda command: None)
    service = service or f"abk-acceptance-{uuid.uuid4().hex[:12]}"

    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    app = scratch_app(tmp_path / "app")
    git(app, "remote", "add", "origin", str(remote))
    git(app, "push", "-q", "origin", "main")

    planning = init_repo(tmp_path / "planning")
    change = planning / "openspec" / "changes" / CHANGE
    (change / "specs" / "marker").mkdir(parents=True)
    (planning / "openspec" / "config.yaml").write_text("schema: spec-driven\n")
    (change / "proposal.md").write_text(
        "## Why\n\nThe app needs a marker.\n\n## What Changes\n\n- Add `marker()`.\n\n"
        "## Impact\n\n- app: one module.\n"
    )
    (change / "specs" / "marker" / "spec.md").write_text(
        "## ADDED Requirements\n\n### Requirement: A marker\nThe app SHALL expose `marker()`.\n\n"
        "#### Scenario: Reading it\n- **WHEN** `marker()` is called\n"
        '- **THEN** it returns "marked"\n'
    )
    (change / "tasks.md").write_text(TASKS)
    (planning / "abk.yaml").write_text(
        f"repos:\n  app:\n    path: {app}\n    slug: example/app\n"
        "    profile: python-uv\n    languages: [python]\n"
        f"{scratch.runtimes_yaml}"
    )
    git(planning, "add", "-A")
    git(planning, "commit", "-q", "-m", "plan")

    with FakeGitHub(first_number=7) as host:
        env = {
            **process_env(host, tmp_path / "bin", tmp_path / "gh-calls.txt"),
            **scratch.env,
            "ABK_CONFIG": str(planning / "abk.yaml"),
            "ABK_WORKTREE_ROOT": str(tmp_path / "worktrees"),
            "ABK_OTEL_ENABLED": "1",
            "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": traces,
            "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT": metrics,
            "OTEL_SERVICE_NAME": service,
        }
        scratch_state = Scratch(
            planning=planning,
            remote=remote,
            state=Installation(config.load(planning / "abk.yaml"), planning).state_dir,
            env=env,
            host=host,
        )
        register_scratch(scratch_state)
        tick = run_tick(scratch_state)
        missed = host.unrouted()
    assert missed == [], (
        f"the forge called routes the fake host does not serve: {missed}\n{tick.output}"
    )
    return Built(scratch=scratch_state, tick=tick, service=service, sink=sink)


def get_json(url: str) -> Any:
    with urllib.request.urlopen(url, timeout=15) as response:  # noqa: S310
        return json.load(response)


def eventually(look: Callable[[], Any], wait: float) -> Any:
    """What `look` returns once it is truthy, or its last answer after `wait`."""
    deadline = time.monotonic() + wait
    while True:
        try:
            found = look()
        except OSError:
            found = None
        if found or time.monotonic() >= deadline:
            return found
        time.sleep(3)


def logged(sink: TelemetryScratch, path: str) -> list[bytes]:
    """The bodies the local sink's receiver was sent on `path`, in order."""
    assert sink.log is not None
    lines = [json.loads(line) for line in sink.log.read_text().splitlines()]
    return [base64.b64decode(line["body"]) for line in lines if line["path"] == path]


def service_of(resource: Any) -> str:
    return next((a.value.string_value for a in resource.attributes if a.key == "service.name"), "")


def attributes_of(attributes: Any) -> dict[str, str]:
    return {a.key: a.value.string_value for a in attributes}


def local_spans(sink: TelemetryScratch, service: str) -> list[Any]:
    """Every span the run's service sent to the local sink."""
    requests = [ExportTraceServiceRequest.FromString(b) for b in logged(sink, "/v1/traces")]
    return [
        span
        for request in requests
        for resource in request.resource_spans
        if service_of(resource.resource) == service
        for scope in resource.scope_spans
        for span in scope.spans
    ]


def find_trace_ids(sink: TelemetryScratch, service: str) -> list[str]:
    """The sink's traces by the unit id and the run's service name: the trace store's search API
    for `otel`, the logged spans for `local`."""
    if sink.log is not None:
        return sorted(
            {
                span.trace_id.hex()
                for span in local_spans(sink, service)
                if attributes_of(span.attributes).get("unit.id") == UNIT_ID
            }
        )
    base = sink.traces_url.rstrip("/")
    tags = urllib.parse.quote(f'unit.id="{UNIT_ID}" service.name="{service}"')
    found = get_json(f"{base}/api/search?tags={tags}&limit=20")
    return [trace["traceID"] for trace in found.get("traces", [])]


def spans_of(sink: TelemetryScratch, service: str, trace_id: str) -> list[dict[str, Any]]:
    """Every span of a trace: the logged spans for `local`, in the trace store's own JSON for
    `otel`, whichever envelope (`batches` or `resourceSpans`, possibly under `trace`) it answers
    with."""
    if sink.log is not None:
        return [
            {
                "name": span.name,
                "spanId": span.span_id.hex(),
                "parentSpanId": span.parent_span_id.hex(),
            }
            for span in local_spans(sink, service)
            if span.trace_id.hex() == trace_id
        ]
    base = sink.traces_url.rstrip("/")
    body = get_json(f"{base}/api/traces/{trace_id}")
    body = body.get("trace", body)
    resources = body.get("batches") or body.get("resourceSpans") or []
    return [
        span
        for resource in resources
        for scope in (
            resource.get("scopeSpans") or resource.get("instrumentationLibrarySpans") or []
        )
        for span in scope.get("spans", [])
    ]


def series_of(sink: TelemetryScratch, service: str, metric: str) -> list[dict[str, str]]:
    """Every series of `metric` the run pushed: the labels of the logged data points for `local`,
    the metrics store's query API for `otel`."""
    if sink.log is not None:
        requests = [ExportMetricsServiceRequest.FromString(b) for b in logged(sink, "/v1/metrics")]
        return [
            attributes_of(point.attributes)
            for request in requests
            for resource in request.resource_metrics
            if service_of(resource.resource) == service
            for scope in resource.scope_metrics
            for found in scope.metrics
            if found.name.replace(".", "_").startswith(metric)
            for point in (*found.histogram.data_points, *found.sum.data_points)
        ]
    base = sink.metrics_url.rstrip("/")
    selector = f'{{__name__=~"{metric}.*",job=~".*{service}"}}'
    found = get_json(f"{base}/api/v1/series?match[]={urllib.parse.quote(selector)}")
    return found.get("data", [])


@pytest.fixture(scope="module", params=TELEMETRY_PARAMS)
def sink(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[TelemetryScratch]:
    """The telemetry value's sink, up for the module."""
    with telemetry_scratch(request.param, tmp_path_factory.mktemp("telemetry-sink")) as scratch:
        yield scratch


@pytest.fixture(scope="module", params=RUNTIME_PARAMS)
def runtime(request: pytest.FixtureRequest) -> str:
    return request.param


@pytest.fixture(scope="module")
def sink_tick(
    runtime: str, sink: TelemetryScratch, tmp_path_factory: pytest.TempPathFactory
) -> Built:
    """One tick on the runtime, pointed at the sink's intake."""
    return build_unit(
        tmp_path_factory.mktemp("telemetry-run"),
        runtime,
        tmp_path_factory,
        sink,
        traces=sink.traces_endpoint,
        metrics=sink.metrics_endpoint,
    )


def test_a_ticks_trace_is_found_in_the_sink_by_the_unit_id(sink_tick: Built) -> None:
    assert sink_tick.tick.returncode == 0, sink_tick.tick.output
    commits_on_unit_branch(sink_tick.scratch, BRANCH, sink_tick.tick)

    trace_ids = eventually(lambda: find_trace_ids(sink_tick.sink, sink_tick.service), INGEST_WAIT)
    assert trace_ids, f"no trace for {UNIT_ID} was found\n{sink_tick.tick.output}"

    spans = spans_of(sink_tick.sink, sink_tick.service, trace_ids[0])
    by_id = {span["spanId"]: span for span in spans}
    roots = [span for span in spans if not span.get("parentSpanId")]
    assert [span["name"] for span in roots] == ["tick"], (
        [span["name"] for span in spans],
        sink_tick.tick.output,
    )
    unit = next((span for span in spans if span["name"] == "unit"), None)
    assert unit is not None, ([span["name"] for span in spans], sink_tick.tick.output)
    assert by_id[unit["parentSpanId"]]["name"] == "tick"
    steps = [span for span in spans if span.get("parentSpanId") == unit["spanId"]]
    assert steps, f"the unit span has no step span below it\n{sink_tick.tick.output}"


def test_a_ticks_duration_series_are_in_the_sink_without_a_unit_id(sink_tick: Built) -> None:
    assert sink_tick.tick.returncode == 0, sink_tick.tick.output
    sink, service = sink_tick.sink, sink_tick.service

    unit_series = eventually(lambda: series_of(sink, service, "abk_unit_duration"), INGEST_WAIT)
    step_series = eventually(lambda: series_of(sink, service, "abk_step_duration"), INGEST_WAIT)
    assert unit_series, f"no abk.unit.duration series\n{sink_tick.tick.output}"
    assert step_series, f"no abk.step.duration series\n{sink_tick.tick.output}"

    assert any(
        {"repo", "tier", "outcome"} <= series.keys() and series["repo"] == "app"
        for series in unit_series
    ), (unit_series, sink_tick.tick.output)
    assert any({"step", "outcome"} <= series.keys() for series in step_series), (
        step_series,
        sink_tick.tick.output,
    )

    # Cardinality is bounded: no label of any series is, or names, a unit.
    forbidden_names = {"unit", "unit_id", "unit.id", "change"}
    for series in unit_series + step_series:
        assert not forbidden_names & series.keys(), series
        assert UNIT_ID not in series.values(), series
        assert CHANGE not in series.values(), series


def test_a_tick_with_an_unreachable_sink_finishes_and_writes_nothing(
    runtime: str, sink: TelemetryScratch, tmp_path: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    dead = closed_endpoint()

    ticked = build_unit(
        tmp_path,
        runtime,
        tmp_path_factory,
        sink,
        traces=f"{dead}/v1/traces",
        metrics=f"{dead}/v1/metrics",
    )

    assert ticked.tick.returncode == 0, ticked.tick.output
    commits_on_unit_branch(ticked.scratch, BRANCH, ticked.tick)

    # Guards against the exporter falling back to the SDK's default endpoint
    # (localhost:4318), which the sink's intake may be listening on.
    output = ticked.tick.output
    assert not eventually(lambda: find_trace_ids(sink, ticked.service), QUIET_WAIT), output
    assert not series_of(sink, ticked.service, "abk_unit_duration"), output
    assert not series_of(sink, ticked.service, "abk_step_duration"), output
