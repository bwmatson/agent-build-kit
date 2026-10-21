"""The web UI over a real scratch installation with a real Claude: a unit built by a real
`claude`, then read, watched, chatted with and requeued through `abk serve`'s API, and a session
started outside the pipeline continued.

`abk tick` runs as a process against a scratch planning repo and a scratch code repo with a bare
remote, and only the code host is faked. The server runs in this process over the same state, as
`abk serve` would beside the ticks. The walk of the unit is `walk_unit_through_review`
(`tests/integration/unit_walk.py`), which is neutral to the runtime so the ACP half reuses it.

Needs a logged-in `claude`, node for the OpenSpec CLI and uv. Bills on demand and takes
minutes, so it is marked `local_stack` and excluded from the default suite; run it with
`uv run pytest -m local_stack tests/integration/test_serve_over_scratch_installation.py`.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from agent_build_kit.serve.server import start_server
from tests.chat_serving import holding_process, turn
from tests.forges.github_server import FakeGitHub
from tests.integration.unit_walk import SAY_OK, WAIT, finished, walk_unit_through_review
from tests.marker_scratch import TASKS, Scratch, build_scratch, serving_host
from tests.runtime_scratch import CLAUDE_CODE_PARAMS, runtime_scratch

pytestmark = [
    pytest.mark.local_stack,
    pytest.mark.skipif(shutil.which("npx") is None, reason="npx is not on PATH"),
    pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not on PATH"),
    pytest.mark.skipif(shutil.which("claude") is None, reason="claude is not on PATH"),
]


@pytest.fixture(scope="module")
def github_host() -> Iterator[FakeGitHub]:
    yield from serving_host()


@pytest.fixture(scope="module")
def scratch(
    request: pytest.FixtureRequest,
    tmp_path_factory: pytest.TempPathFactory,
    github_host: FakeGitHub,
) -> Scratch:
    """The scratch installation for the runtime the test is parametrized with."""
    runtime = runtime_scratch(request.param, tmp_path_factory, lambda command: None)
    return build_scratch(tmp_path_factory.mktemp("serve-live"), github_host, runtime, tasks=TASKS)


@pytest.fixture
def api(scratch: Scratch, workspace: object) -> Iterator[httpx.Client]:
    """The UI's server over the scratch installation, activated as `abk serve` does, and
    starting its agents with the scratch's environment. After `workspace`, whose default
    configuration it replaces."""
    installation = scratch.installation
    installation.activate()
    with (
        start_server(installation, agent_environment=scratch.env) as server,
        httpx.Client(base_url=server.url, timeout=WAIT) as client,
    ):
        yield client


def claude_session_elsewhere(project: Path) -> str:
    """A session a person started in their own directory with `claude`, as an editor would."""
    project.mkdir()
    ran = subprocess.run(
        ["claude", "-p", SAY_OK, "--output-format", "json"],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=WAIT,
    )
    assert ran.returncode == 0, ran.stdout + ran.stderr
    return json.loads(ran.stdout)["session_id"]


def session_of(events: list[dict[str, Any]]) -> str:
    """The id of the session a streamed turn ran in."""
    return next(
        e["value"]["id"] for e in events if e["type"] == "CUSTOM" and e["name"] == "session"
    )


@pytest.mark.parametrize("scratch", CLAUDE_CODE_PARAMS, indirect=True)
def test_the_ui_shows_a_unit_a_real_claude_built_and_works_it_through_review(
    scratch: Scratch, api: httpx.Client
) -> None:
    walk_unit_through_review(scratch, api, scratch.runtime)


@pytest.mark.parametrize("scratch", CLAUDE_CODE_PARAMS, indirect=True)
def test_a_session_started_elsewhere_is_continued_in_place_or_forked_when_held(
    scratch: Scratch, api: httpx.Client, tmp_path_factory: pytest.TempPathFactory
) -> None:
    elsewhere = claude_session_elsewhere(tmp_path_factory.mktemp("elsewhere") / "project")
    found = {s["id"]: s for s in api.get("/api/sessions").json()["sessions"]}
    assert elsewhere in found and found[elsewhere]["runtime"] == "claude_code"
    detail = api.get(f"/api/sessions/claude_code/{elsewhere}").json()
    assert "continue" in detail["actions"], detail

    # No process holds it: the turn resumes the session in place.
    url = f"/api/sessions/claude_code/{elsewhere}/continue"
    resumed = turn(api, url, {"tab": "resume", "prompt": SAY_OK}, timeout=WAIT)
    assert finished(resumed), resumed
    assert session_of(resumed) == elsewhere, resumed

    # A process holds it, as an editor does: the turn forks into a session of its own.
    with holding_process(elsewhere):
        held = turn(api, url, {"tab": "fork", "prompt": SAY_OK}, timeout=WAIT)
    assert finished(held), held
    assert session_of(held) != elsewhere, held
