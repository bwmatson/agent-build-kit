"""What a spawned asker process runs: it rebuilds the faked endpoint, the credential and
anchor paths and the default config that a forked child used to inherit."""

import multiprocessing
import threading
import urllib.request
from collections.abc import Callable
from pathlib import Path

from agent_build_kit import config as config_module
from agent_build_kit.config import WorkspaceConfig
from agent_build_kit.pipeline import usage_guard
from agent_build_kit.pipeline.usage_guard import read_live_usage
from tests.usage_host import Response, payload


def slow_urlopen(calls: Path, answer: dict, call_seconds: float) -> Callable[..., Response]:
    """An endpoint that answers after `call_seconds`; every call made to it, in any
    process, is written to `calls`."""

    def urlopen(request: object, timeout: float | None = None) -> Response:
        with calls.open("a") as record:
            record.write("call\n")
        threading.Event().wait(call_seconds)
        return Response(payload(**answer))

    return urlopen


def asking_in_a_process(
    asks: int,
    results: "multiprocessing.Queue",
    home: Path,
    calls: Path,
    answer: dict,
    call_seconds: float,
) -> None:
    usage_guard.CREDENTIALS_PATH = home / "no-credentials.json"
    usage_guard.DEFAULT_ANCHOR_PATH = home / ".claude.json"
    urllib.request.urlopen = slow_urlopen(calls, answer, call_seconds)  # type: ignore[assignment]
    config_module.activate(WorkspaceConfig(), None)
    for _ in range(asks):
        reading = read_live_usage()
        results.put(None if reading is None else (reading.source, reading.session_pct))
