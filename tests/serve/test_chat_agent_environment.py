"""The agents the server starts get the environment it was given (spec:
acceptance-server-runs-in-the-scratch-environment, group 1): a turn on a build session, a new
session, a continued one and the resume check all start their agent in it, and a server given
none leaves them the process's.

The agent is a real process (`tests/runtimes/acp_agent.py`) that records the variables it
started with. See `tests/chat_serving.py` for the endpoints.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

import httpx
import pytest

import agent_build_kit.cli.serve_cmd as serve_cmd
import agent_build_kit.serve as serve_package
from agent_build_kit.installation import Installation
from agent_build_kit.serve.chat import Chat
from agent_build_kit.serve.server import start_server
from tests.chat_serving import record_session, recorded_acp_session, turn, unit_worktree
from tests.runtimes.acp_agent import ENVIRONMENT, SESSION, requests, use_agent
from tests.serving import seed_pipeline

GIVEN = "ABK_TEST_GIVEN"
ONLY_HERE = "ABK_TEST_ONLY_IN_THE_PROCESS"
WATCHED = (GIVEN, ONLY_HERE, "PYTEST_CURRENT_TEST")
REVIEW = "/api/units/feature/2"

# A session id on a command line (a fake agent listing it) is seen by every server on the
# machine, so these cannot run beside each other.


@pytest.fixture(autouse=True)
def process_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ONLY_HERE, "from-the-process")
    monkeypatch.delenv(GIVEN, raising=False)


@pytest.fixture
def pipeline(inst: Installation) -> Installation:
    seed_pipeline(inst)
    unit_worktree(inst, "feature/2")
    return inst


@pytest.fixture
def record(tmp_path: Path) -> Path:
    path = tmp_path / "agent.jsonl"
    use_agent(
        path,
        resume=True,
        list_sessions=True,
        sessions=(SESSION,),
        sessions_when=GIVEN,
        watch=WATCHED,
    )
    return path


def scratch() -> dict[str, str]:
    return {"PATH": os.environ["PATH"], GIVEN: "given"}


def agents_started(record: Path) -> list[dict[str, str | None]]:
    return requests(record, ENVIRONMENT)


def assert_all_in_the_given_environment(record: Path) -> None:
    started = agents_started(record)
    assert started, "no agent was started"
    for seen in started:
        assert seen[GIVEN] == "given"
        assert seen[ONLY_HERE] is None
        assert seen["PYTEST_CURRENT_TEST"] is None


def test_a_turn_on_a_build_session_runs_in_the_given_environment(
    pipeline: Installation, record: Path
) -> None:
    record_session(pipeline, "feature/2", SESSION, runtime="acp")

    with start_server(pipeline, agent_environment=scratch()) as server:
        with httpx.Client(base_url=server.url) as api:
            turn(api, f"{REVIEW}/chat", {"tab": "t1", "prompt": "Hello."})

    assert requests(record, "session/prompt")
    assert_all_in_the_given_environment(record)


def test_a_new_session_runs_in_the_given_environment(pipeline: Installation, record: Path) -> None:
    body = {"tab": "t1", "runtime": "acp", "unit": "feature/2", "prompt": "Look around."}

    with start_server(pipeline, agent_environment=scratch()) as server:
        with httpx.Client(base_url=server.url) as api:
            turn(api, "/api/sessions", body)

    assert requests(record, "session/new")
    assert_all_in_the_given_environment(record)


def test_a_continued_session_runs_in_the_given_environment(
    pipeline: Installation, record: Path
) -> None:
    recorded_acp_session(pipeline, SESSION)

    with start_server(pipeline, agent_environment=scratch()) as server:
        with httpx.Client(base_url=server.url) as api:
            turn(api, f"/api/sessions/acp/{SESSION}/continue", {"tab": "t1", "prompt": "Go on."})

    assert requests(record, "session/resume"), "the session was not resumed in place"
    assert_all_in_the_given_environment(record)


def test_the_resume_check_runs_in_the_given_environment(
    pipeline: Installation, record: Path
) -> None:
    recorded_acp_session(pipeline, SESSION)

    with start_server(pipeline, agent_environment=scratch()) as server:
        with httpx.Client(base_url=server.url) as api:
            opened = api.get(f"/api/sessions/acp/{SESSION}").json()

    assert "continue" in opened["actions"]
    assert_all_in_the_given_environment(record)


def test_a_server_given_no_environment_leaves_its_agents_the_process_environment(
    pipeline: Installation, record: Path
) -> None:
    body = {"tab": "t1", "runtime": "acp", "unit": "feature/2", "prompt": "Look around."}

    with start_server(pipeline) as server:
        with httpx.Client(base_url=server.url) as api:
            turn(api, "/api/sessions", body)

    (seen,) = agents_started(record)
    assert seen[ONLY_HERE] == "from-the-process"
    assert seen["PYTEST_CURRENT_TEST"]


def test_the_request_a_chat_builds_carries_the_environment(pipeline: Installation) -> None:
    chat = Chat(
        pipeline, units=lambda: [], recorded_session=lambda unit: None, agent_environment=scratch()
    )

    request = chat.request({}, "Hello.", pipeline.root)

    assert request.environment == scratch()


def calls_in(path: Path, name: str) -> list[tuple[str, ast.Call]]:
    """Each call of `name` in the file, with the function it sits in (`Class.method`)."""
    tree = ast.parse(path.read_text())
    found: list[tuple[str, ast.Call]] = []

    def visit(node: ast.AST, scope: tuple[str, ...]) -> None:
        for child in ast.iter_child_nodes(node):
            inner = scope
            if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                inner = (*scope, child.name)
            if (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Name)
                and child.func.id == name
            ):
                found.append((".".join(scope), child))
            visit(child, inner)

    visit(tree, ())
    return found


def test_no_agent_request_is_built_under_serve_outside_chat_request() -> None:
    serve_dir = Path(serve_package.__file__).parent

    built = {
        f"{path.name}:{scope}"
        for path in serve_dir.rglob("*.py")
        for scope, _ in calls_in(path, "AgentRequest")
    }

    assert built == {"chat.py:Chat.request"}


def test_abk_serve_starts_the_server_with_no_agent_environment() -> None:
    (call,) = [call for _, call in calls_in(Path(serve_cmd.__file__), "start_server")]

    assert "agent_environment" not in {keyword.arg for keyword in call.keywords}
