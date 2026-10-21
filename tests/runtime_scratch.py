"""The dimension helper of the live tests: the scratch installation built for one runtime, and the
telemetry sink built for one telemetry value."""

from __future__ import annotations

import base64
import gzip
import json
import os
import shlex
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from _pytest.mark.structures import ParameterSet
from pydantic import Field

from agent_build_kit import claude_account
from agent_build_kit.model import Frozen
from tests.agent_home import TempFactory, agent_home

RUNTIMES = ("claude_code", "acp")
TELEMETRY_VALUES = ("otel", "local")
AGENT_COMMAND = "ABK_ACCEPTANCE_ACP_COMMAND"
USAGE_GUARD = "ABK_USAGE_GUARD"

# One parameter per runtime, each carrying its one `runtime_<name>` tag.
RUNTIME_PARAMS: list[ParameterSet] = [
    pytest.param(name, marks=getattr(pytest.mark, f"runtime_{name}")) for name in RUNTIMES
]
# One parameter per telemetry value, each carrying its one `telemetry_<name>` tag.
TELEMETRY_PARAMS: list[ParameterSet] = [
    pytest.param(name, marks=getattr(pytest.mark, f"telemetry_{name}")) for name in TELEMETRY_VALUES
]
# The selection of those for the tests that run on Claude Code alone, until the ACP variants
# are added.
CLAUDE_CODE_PARAMS: list[ParameterSet] = [p for p in RUNTIME_PARAMS if p.values[0] == "claude_code"]


class RuntimeScratch(Frozen):
    """What a live test needs of a runtime: the `runtimes` entry for `abk.yaml` ("" when none),
    the process environment its `abk` runs with, and the agent's command ([] when none)."""

    runtime: str
    runtimes_yaml: str
    env: dict[str, str] = Field(repr=False)
    command: list[str]


def runtime_scratch(
    runtime: str,
    tmp_path_factory: TempFactory,
    start_check: Callable[[list[str]], None],
    usage_guard: bool = False,
) -> RuntimeScratch:
    """The setup for `runtime`; `start_check` is asked, with the agent's command, to confirm the
    agent starts. A Claude Code tick takes no usage reading unless `usage_guard` (a test about the
    guard) is set. Fails, never skips, when the runtime's agent command setting is missing."""
    env = dict(agent_home(tmp_path_factory).env)
    if runtime != "acp":
        env.update({n: os.environ[n] for n in claude_account.NAMES if n in os.environ})
        env["ABK_RUNTIME"] = runtime
        if not usage_guard:
            env[USAGE_GUARD] = "off"
        return RuntimeScratch(runtime=runtime, runtimes_yaml="", env=env, command=[])
    line = os.environ.get(AGENT_COMMAND, "")
    if not line:
        pytest.fail(f"{AGENT_COMMAND} names no agent: this run needs a real one on the host")
    command = shlex.split(line)
    start_check(command)
    return RuntimeScratch(
        runtime=runtime,
        runtimes_yaml=f"runtimes:\n  acp:\n    command: {command}\n",
        env={**env, "ABK_RUNTIME": "acp"},
        command=command,
    )


# The shared stack's dev instance, named by the variables a person sets for acceptance runs.
TRACES_ENDPOINT = "ABK_ACCEPTANCE_TRACES_ENDPOINT"
METRICS_ENDPOINT = "ABK_ACCEPTANCE_METRICS_ENDPOINT"
TRACES_URL = "ABK_ACCEPTANCE_TRACES_URL"
METRICS_URL = "ABK_ACCEPTANCE_METRICS_URL"


def require_env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        pytest.fail(f"{name} is not set: this run needs the shared stack's dev instance up")
    return value


class TelemetryScratch(Frozen):
    """What a live test needs of a telemetry value: where a tick pushes its traces and metrics,
    and where to read them back. `otel` is the shared stack (its query URLs are set); `local` is
    a file (`log`, one JSON line per request) written by a receiver on a free port."""

    value: str
    traces_endpoint: str
    metrics_endpoint: str
    traces_url: str = ""
    metrics_url: str = ""
    log: Path | None = None


def _receiver(log: Path) -> ThreadingHTTPServer:
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            if self.headers.get("Content-Encoding") == "gzip":
                body = gzip.decompress(body)
            line = json.dumps({"path": self.path, "body": base64.b64encode(body).decode()})
            with lock, log.open("a") as out:
                out.write(line + "\n")
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            pass

    return ThreadingHTTPServer(("127.0.0.1", 0), Handler)


@contextmanager
def telemetry_scratch(value: str, directory: Path) -> Iterator[TelemetryScratch]:
    """The sink for `value`. `otel` fails, never skips, naming a missing `ABK_ACCEPTANCE_*`
    variable; `local` runs a receiver that writes each request to a file under `directory`, and
    stops it afterwards."""
    if value == "otel":
        yield TelemetryScratch(
            value=value,
            traces_endpoint=require_env(TRACES_ENDPOINT),
            metrics_endpoint=require_env(METRICS_ENDPOINT),
            traces_url=require_env(TRACES_URL),
            metrics_url=require_env(METRICS_URL),
        )
        return
    log = directory / "telemetry.jsonl"
    log.touch()
    server = _receiver(log)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield TelemetryScratch(
            value=value,
            traces_endpoint=f"{base}/v1/traces",
            metrics_endpoint=f"{base}/v1/metrics",
            log=log,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
