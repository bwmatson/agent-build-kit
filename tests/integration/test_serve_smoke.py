"""The one test of `abk serve` over a real socket: it listens on a loopback port, lists the
sessions, streams a turn to a real client and shuts down (spec: chat-tests).

Every other chat test calls the application in-process; what only a socket shows (a stream
flushed as it is written, a connection that closes) is checked here, and unit-test does not run
it.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from agent_build_kit.config import dump
from agent_build_kit.installation import Installation
from agent_build_kit.serve.server import start_server
from agent_build_kit.settings import settings
from tests.chat_serving import events_of, use_claude
from tests.conftest import make_installation
from tests.runtimes.claude_cli import finished_build
from tests.serving import seed_pipeline

pytestmark = pytest.mark.integration


@pytest.fixture
def pipeline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Installation:
    installation = make_installation(
        tmp_path / "planning", planning={"worktree_root": str(tmp_path / "worktrees")}
    )
    (installation.root / "abk.yaml").write_text(dump(installation.config))
    monkeypatch.chdir(installation.root)
    home = tmp_path / "claude-home"
    home.mkdir()
    monkeypatch.setattr(settings, "claude_home", home)
    seed_pipeline(installation)
    return installation


def test_the_server_lists_sessions_and_streams_a_turn_over_a_loopback_socket(
    pipeline: Installation, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout = pipeline.checkouts["app"]
    checkout.mkdir(parents=True, exist_ok=True)
    use_claude(monkeypatch, finished_build(checkout, "Hello."))

    with start_server(pipeline) as server, httpx.Client(base_url=server.url) as client:
        assert server.host == "127.0.0.1"
        assert server.port != 0
        assert client.get("/api/sessions").json() == {"sessions": []}

        with client.stream(
            "POST",
            "/api/sessions",
            json={
                "tab": "t1",
                "runtime": "claude_code",
                "model": "sonnet",
                "repo": "app",
                "prompt": "Hi.",
            },
            timeout=30,
        ) as response:
            assert response.status_code == 200
            events = list(events_of(response))

    assert any(e["type"] == "CUSTOM" and e["name"] == "session" for e in events)
    assert events[-1]["type"] == "RUN_FINISHED"
