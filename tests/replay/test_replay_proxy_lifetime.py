"""The replay proxy outlives the build it serves: it answers for as long as the child tick
runs, past the default time limit when the test is e2e, and it stops only after the child is
gone, even when a time limit is what ends the wait.

Run as inner pytest sessions with the time-limit plugin, a one-second default limit, and a
generated `local_stack` test that runs a child tick through the `replay` fixture's proxy."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.replay.fake_upstream import FakeUpstream
from tests.replay.support import ENV, UPSTREAM, run_session

INNER = """
import os
import sys
from pathlib import Path

import pytest

from agent_build_kit.config import ReplayConfig, ReplayUpstream
from tests import scratch_tick
from tests.scratch_fakes import hand_scratch
from tests.scratch_tick import run_tick

pytestmark = pytest.mark.local_stack

OUT = Path(os.environ["LIFETIME_OUT"])


@pytest.fixture
def replay_config():
    upstream = ReplayUpstream(
        name="{name}", url=os.environ["LIFETIME_UPSTREAM"], kind="deterministic", env=["{env}"]
    )
    return ReplayConfig(upstreams=[upstream], directory=OUT / "cassettes")


@pytest.fixture
def replay_in_stack():
    return None


@pytest.fixture
def probe(replay):
    # Torn down before the proxy is closed, which the plugin does from the teardown report.
    yield
    pid = int((OUT / "pid").read_text())
    try:
        os.kill(pid, 0)
        alive = True
    except ProcessLookupError:
        alive = False
    (OUT / "alive").write_text(str(alive))


ASKS = f'''#!{{sys.executable}}
import os
import threading

import httpx

threading.Event().wait(1.5)
reply = httpx.get(os.environ["{env}"] + "/later")
open(os.environ["LIFETIME_OUT"] + "/status", "w").write(str(reply.status_code))
'''
SLEEPS = f"#!/bin/sh\\necho $$ > {{OUT / 'pid'}}\\nexec sleep 60\\n"


def tick_of(program_text, monkeypatch, env):
    # The tick is a stand-in `abk`: a long-running child the shared tick helper runs.
    program = OUT / "abk-stand-in"
    program.write_text(program_text)
    program.chmod(0o755)
    monkeypatch.setattr(scratch_tick, "ABK", program)
    scratch = hand_scratch(OUT / "scratch")
    scratch.planning.mkdir()
    scratch.env.update(env)
    return run_tick(scratch)


def test_answered(replay, probe, monkeypatch):
    (OUT / "pid").write_text("0")
    env = {{**os.environ, **replay.environment()}}
    assert tick_of(ASKS, monkeypatch, env).returncode == 0


def test_limit_ends_the_wait(replay, probe, monkeypatch):
    tick_of(SLEEPS, monkeypatch, dict(os.environ))
"""


def run(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
    upstream: FakeUpstream,
    tmp_path: Path,
    test: str,
    e2e_limit: int,
) -> pytest.RunResult:
    monkeypatch.setenv("LIFETIME_OUT", str(tmp_path))
    monkeypatch.setenv("LIFETIME_UPSTREAM", upstream.url)
    return run_session(
        pytester,
        monkeypatch,
        "live",
        "-p",
        "tests.time_limit",
        "--test-time-limit=1",
        f"--e2e-test-time-limit={e2e_limit}",
        f"test_lifetime.py::{test}",
        test_lifetime=INNER.format(name=UPSTREAM, env=ENV),
    )


def test_a_request_after_the_default_limit_would_have_fired_is_still_answered(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
    upstream: FakeUpstream,
    tmp_path: Path,
) -> None:
    result = run(pytester, monkeypatch, upstream, tmp_path, "test_answered", 30)

    result.assert_outcomes(passed=1)
    assert (tmp_path / "status").read_text() == "200"
    assert [seen.path for seen in upstream.seen] == ["/later"]


def test_the_child_is_gone_before_the_proxy_stops_when_a_limit_ends_the_wait(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
    upstream: FakeUpstream,
    tmp_path: Path,
) -> None:
    result = run(pytester, monkeypatch, upstream, tmp_path, "test_limit_ends_the_wait", 1)

    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*exceeded the e2e-test time limit of 1 seconds*"])
    assert (tmp_path / "alive").read_text() == "False"
