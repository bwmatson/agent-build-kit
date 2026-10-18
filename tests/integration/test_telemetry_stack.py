"""A tick's telemetry arriving in the shared stack's trace and metrics stores.

`abk tick` is the real CLI run as a process against a scratch planning repo and
a scratch code repo with a bare remote, with a real agent on this host
(the host's own Claude login) and telemetry switched on through the settings a
person would set. Only GitHub is faked: a fake server speaking the REST API,
reached through `ABK_GITHUB_API_URL`, with `gh auth token` the one command left as
a script.

The stores are the stack's own, read back through the queries a person would
use: the trace store's search API by unit id, and the metrics store's query API
by metric name. The dev instance must be up; its published ports are named by:

- `ABK_ACCEPTANCE_TRACES_ENDPOINT`   the trace intake, a full OTLP/HTTP URL
- `ABK_ACCEPTANCE_METRICS_ENDPOINT`  the metrics intake, a full OTLP/HTTP URL
- `ABK_ACCEPTANCE_TRACES_URL`        the trace store's base URL (search API)
- `ABK_ACCEPTANCE_METRICS_URL`       the metrics store's base URL (query API)

The fixture unit is built once, for `claude_code`, under that runtime's one tag. The
`acp` parameters are added by a separate change.

Every run is told apart in the stores by a service name of its own, so a store
that already holds earlier runs does not answer for this one.

Needs the dev stack, the host's Claude Code login, node for the OpenSpec CLI
and uv. Bills on demand and takes minutes, so it is marked e2e-test and excluded
from the default suite.
"""

from __future__ import annotations

import json
import os
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
from pydantic import Field

from agent_build_kit import config
from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from tests.factories import git, init_repo, scratch_app
from tests.forges.github_server import FakeGitHub
from tests.forges.process_host import process_env
from tests.runtime_scratch import runtime_scratch
from tests.scratch_tick import TickResult, commits_on_unit_branch, register_scratch, run_tick

pytestmark = [
    pytest.mark.local_stack,
    pytest.mark.skipif(shutil.which("npx") is None, reason="npx is not on PATH"),
    pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not on PATH"),
]

CHANGE = "add-marker"
BRANCH = f"spec/{CHANGE}/1"
UNIT_ID = f"{CHANGE}/1"
TRACES_ENDPOINT = "ABK_ACCEPTANCE_TRACES_ENDPOINT"
METRICS_ENDPOINT = "ABK_ACCEPTANCE_METRICS_ENDPOINT"
TRACES_URL = "ABK_ACCEPTANCE_TRACES_URL"
METRICS_URL = "ABK_ACCEPTANCE_METRICS_URL"

# How long the stores get to make a pushed trace or series searchable.
INGEST_WAIT = 90.0
# How long a store that should hold nothing is given to prove it.
QUIET_WAIT = 20.0

# Why the dead-collector check runs on Claude alone: the exporter is the kit's own and sits
# above the runtime, so a build on a second runtime would exercise the same code.
DEAD_COLLECTOR_REASON = (
    "the exporter does not depend on the agent; a build on a second runtime adds no coverage"
)

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


def require_env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        pytest.fail(f"{name} is not set: this run needs the shared stack's dev instance up")
    return value


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
    *,
    traces: str,
    metrics: str,
    service: str | None = None,
) -> Built:
    """Build the fixture unit in one tick on `runtime` with telemetry on, pointed at
    `traces` and `metrics`, under a service name of its own."""
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
    return Built(scratch=scratch_state, tick=tick, service=service)


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


def find_trace_ids(service: str) -> list[str]:
    """The trace store's search API, by the unit id and the run's service name."""
    base = require_env(TRACES_URL).rstrip("/")
    tags = urllib.parse.quote(f'unit.id="{UNIT_ID}" service.name="{service}"')
    found = get_json(f"{base}/api/search?tags={tags}&limit=20")
    return [trace["traceID"] for trace in found.get("traces", [])]


def spans_of(trace_id: str) -> list[dict[str, Any]]:
    """Every span of a trace, in the trace store's own JSON, whichever envelope
    (`batches` or `resourceSpans`, possibly under `trace`) it answers with."""
    base = require_env(TRACES_URL).rstrip("/")
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


def series_of(service: str, metric: str) -> list[dict[str, str]]:
    """The metrics store's query API: every series of `metric` the run pushed."""
    base = require_env(METRICS_URL).rstrip("/")
    selector = f'{{__name__=~"{metric}.*",job=~".*{service}"}}'
    found = get_json(f"{base}/api/v1/series?match[]={urllib.parse.quote(selector)}")
    return found.get("data", [])


@pytest.fixture(
    scope="module", params=[pytest.param("claude_code", marks=pytest.mark.runtime_claude_code)]
)
def stack_tick(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[Built]:
    """One tick on the parameter's runtime, pointed at the dev stack's intake."""
    yield build_unit(
        tmp_path_factory.mktemp("telemetry-stack"),
        request.param,
        tmp_path_factory,
        traces=require_env(TRACES_ENDPOINT),
        metrics=require_env(METRICS_ENDPOINT),
    )


def test_a_ticks_trace_is_found_in_the_trace_store_by_the_unit_id(stack_tick: Built) -> None:
    assert stack_tick.tick.returncode == 0, stack_tick.tick.output
    commits_on_unit_branch(stack_tick.scratch, BRANCH, stack_tick.tick)

    trace_ids = eventually(lambda: find_trace_ids(stack_tick.service), INGEST_WAIT)
    assert trace_ids, f"no trace for {UNIT_ID} was found\n{stack_tick.tick.output}"

    spans = spans_of(trace_ids[0])
    by_id = {span["spanId"]: span for span in spans}
    roots = [span for span in spans if not span.get("parentSpanId")]
    assert [span["name"] for span in roots] == ["tick"], (
        [span["name"] for span in spans],
        stack_tick.tick.output,
    )
    unit = next((span for span in spans if span["name"] == "unit"), None)
    assert unit is not None, ([span["name"] for span in spans], stack_tick.tick.output)
    assert by_id[unit["parentSpanId"]]["name"] == "tick"
    steps = [span for span in spans if span.get("parentSpanId") == unit["spanId"]]
    assert steps, f"the unit span has no step span below it\n{stack_tick.tick.output}"


def test_a_ticks_duration_series_are_in_the_metrics_store_without_a_unit_id(
    stack_tick: Built,
) -> None:
    assert stack_tick.tick.returncode == 0, stack_tick.tick.output

    unit_series = eventually(
        lambda: series_of(stack_tick.service, "abk_unit_duration"), INGEST_WAIT
    )
    step_series = eventually(
        lambda: series_of(stack_tick.service, "abk_step_duration"), INGEST_WAIT
    )
    assert unit_series, f"no abk.unit.duration series\n{stack_tick.tick.output}"
    assert step_series, f"no abk.step.duration series\n{stack_tick.tick.output}"

    assert any(
        {"repo", "tier", "outcome"} <= series.keys() and series["repo"] == "app"
        for series in unit_series
    ), (unit_series, stack_tick.tick.output)
    assert any({"step", "outcome"} <= series.keys() for series in step_series), (
        step_series,
        stack_tick.tick.output,
    )

    # Cardinality is bounded: no label of any series is, or names, a unit.
    forbidden_names = {"unit", "unit_id", "unit.id", "change"}
    for series in unit_series + step_series:
        assert not forbidden_names & series.keys(), series
        assert UNIT_ID not in series.values(), series
        assert CHANGE not in series.values(), series


@pytest.mark.runtime_claude_code
def test_a_tick_with_the_endpoint_pointing_at_nothing_finishes_and_writes_nothing(
    tmp_path: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """Claude alone: the exporter does not depend on the agent, so a build on a second runtime
    adds no coverage."""
    dead = closed_endpoint()
    # The stack must be up for "nothing was written" to mean anything.
    require_env(TRACES_URL)
    require_env(METRICS_URL)

    ticked = build_unit(
        tmp_path,
        "claude_code",
        tmp_path_factory,
        traces=f"{dead}/v1/traces",
        metrics=f"{dead}/v1/metrics",
    )

    assert ticked.tick.returncode == 0, ticked.tick.output
    commits_on_unit_branch(ticked.scratch, BRANCH, ticked.tick)

    # Guards against the exporter falling back to the SDK's default endpoint
    # (localhost:4318), which the stack's intake may be listening on.
    output = ticked.tick.output
    assert not eventually(lambda: find_trace_ids(ticked.service), QUIET_WAIT), output
    assert not series_of(ticked.service, "abk_unit_duration"), output
    assert not series_of(ticked.service, "abk_step_duration"), output
