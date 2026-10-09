"""The sessions page: a session an editor holds is read-only and forked, new sessions start in
a unit's worktree, and a session started elsewhere is listed and continued.

Claude is the `claude` binary faked at its stream-json boundary, with the editor's session
files and the process holding one as they are on a machine; ACP is a real agent process
(`tests/runtimes/acp_agent.py`). See `tests/chat_serving.py` for the endpoints.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.lease import Leases, lease_dir
from agent_build_kit.pipeline.transcript import Transcript, TranscriptEvent, transcript_dir
from agent_build_kit.settings import settings
from tests.chat_serving import (
    claude_session_file,
    holding_process,
    prompt_of,
    record_session,
    turn,
    unit_worktree,
    use_claude,
)
from tests.factories import unit
from tests.runtimes.acp_agent import (
    DEFAULT_MODEL,
    EARLIER_TURN,
    MODEL_AT_PROMPT,
    SESSION,
    requests,
    use_agent,
)
from tests.runtimes.claude_cli import SESSION as FAKE_CLAUDE_SESSION
from tests.runtimes.claude_cli import finished_build
from tests.serving import seed_pipeline

# A session id on a command line (an editor holding it, a fake agent listing it) is seen by
# every server on the machine, so these cannot run beside each other.
pytestmark = pytest.mark.serial

EDITOR_SESSION = "0b7e1d52-9c3a-4f8e-b1d6-2a5c7e9f0d31"
IDLE_SESSION = "6d2a8f14-3e5b-4c7a-9f0e-1b8d3c6a2e47"
OLD_ACP = "sess_Ln3Vt8QaRcXe5mJd"


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "claude-home"
    path.mkdir()
    monkeypatch.setattr(settings, "claude_home", path)
    return path


@pytest.fixture
def pipeline(inst: Installation, home: Path) -> Installation:
    """The pipeline, with Claude's sessions under `home`, never the machine's own."""
    seed_pipeline(inst)
    return inst


@pytest.fixture
def editor(home: Path, tmp_path: Path) -> Path:
    """A session started in an editor, in a project of its own."""
    project = tmp_path / "project"
    project.mkdir()
    claude_session_file(home, IDLE_SESSION, project, title="Idle one")
    return claude_session_file(home, EDITOR_SESSION, project, title="Fix the bug")


def listed(api: httpx.Client) -> dict[str, dict[str, Any]]:
    return {s["id"]: s for s in api.get("/api/sessions").json()["sessions"]}


# --- 8.3 a session an editor holds ---------------------------------------------------------


def test_a_session_held_by_a_running_editor_process_is_read_only_with_fork_offered(
    pipeline: Installation, editor: Path, api: httpx.Client
) -> None:
    with holding_process(EDITOR_SESSION):
        opened = api.get(f"/api/sessions/claude_code/{EDITOR_SESSION}").json()

    assert opened["read_only"] is True
    assert "process" in opened["reason"].lower()
    assert "Fix the bug" in str(opened["events"]), "its history is shown"
    assert "fork" in opened["actions"]


def test_a_units_chat_into_a_session_a_process_holds_is_refused(
    pipeline: Installation, editor: Path, api: httpx.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = use_claude(monkeypatch, finished_build(editor.parent, "Hi."))
    record_session(pipeline, "feature/2", EDITOR_SESSION, runtime="claude_code")
    before = editor.read_bytes()

    with holding_process(EDITOR_SESSION):
        tab = api.get("/api/units/feature/2/agent", params={"tab": "t1"}).json()
        written = api.post("/api/units/feature/2/chat", json={"tab": "t1", "prompt": "Hello"})

    assert tab["composer"]["enabled"] is False
    assert "process" in tab["composer"]["reason"].lower()
    assert written.status_code == 409
    assert fake.calls == []
    assert editor.read_bytes() == before


def test_the_sessions_page_marks_which_sessions_a_process_holds(
    pipeline: Installation, editor: Path, api: httpx.Client
) -> None:
    with holding_process(EDITOR_SESSION):
        sessions = listed(api)

    assert sessions[EDITOR_SESSION]["held"] is True
    assert sessions[IDLE_SESSION]["held"] is False


def test_forking_starts_a_new_session_and_never_writes_to_the_first(
    pipeline: Installation, editor: Path, api: httpx.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = use_claude(monkeypatch, finished_build(editor.parent, "Forked."))
    before = editor.read_bytes()

    with holding_process(EDITOR_SESSION):
        events = turn(
            api,
            f"/api/sessions/claude_code/{EDITOR_SESSION}/fork",
            {"tab": "t1", "prompt": "Take it further."},
        )

    argv = fake.calls[0][0]
    assert argv[argv.index("--resume") + 1] == EDITOR_SESSION
    assert "--fork-session" in argv, "the agent forks rather than appending to the editor's file"
    assert "Take it further." in prompt_of(argv)
    started = next(e for e in events if e["type"] == "CUSTOM" and e["name"] == "session")
    assert started["value"]["id"] == FAKE_CLAUDE_SESSION != EDITOR_SESSION
    assert editor.read_bytes() == before


# --- 8.5 a new session -----------------------------------------------------------------------


def test_a_new_claude_session_for_a_unit_starts_in_its_worktree_on_the_chosen_model(
    pipeline: Installation, home: Path, api: httpx.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    tree = unit_worktree(pipeline, "feature/2")
    fake = use_claude(monkeypatch, finished_build(tree, "Hello."))

    events = turn(
        api,
        "/api/sessions",
        {
            "tab": "t1",
            "runtime": "claude_code",
            "model": "sonnet",
            "unit": "feature/2",
            "prompt": "Look around.",
        },
    )

    argv, cwd = fake.calls[0]
    assert cwd == tree
    assert argv[argv.index("--model") + 1] == "sonnet"
    assert "--resume" not in argv
    assert any(e["type"] == "CUSTOM" and e["name"] == "session" for e in events)
    assert Leases(lease_dir(pipeline.state_dir)).holder("feature/2") == "tab:t1"


def test_a_new_acp_session_for_a_unit_starts_in_its_worktree_on_the_chosen_model(
    pipeline: Installation, tmp_path: Path, api: httpx.Client
) -> None:
    tree = unit_worktree(pipeline, "feature/2")
    record = tmp_path / "agent.jsonl"
    use_agent(record)
    assert DEFAULT_MODEL != "deep-2"

    turn(
        api,
        "/api/sessions",
        {
            "tab": "t1",
            "runtime": "acp",
            "model": "deep-2",
            "unit": "feature/2",
            "prompt": "Look around.",
        },
    )

    [opened] = requests(record, "session/new")
    assert Path(opened["cwd"]) == tree
    assert requests(record, MODEL_AT_PROMPT) == [{"model": "deep-2"}]
    assert Leases(lease_dir(pipeline.state_dir)).holder("feature/2") == "tab:t1"


def test_a_new_session_for_a_repo_starts_in_its_checkout(
    pipeline: Installation, home: Path, api: httpx.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout = pipeline.checkouts["app"]
    checkout.mkdir(parents=True, exist_ok=True)
    fake = use_claude(monkeypatch, finished_build(checkout, "Hello."))

    turn(
        api,
        "/api/sessions",
        {"tab": "t1", "runtime": "claude_code", "model": "sonnet", "repo": "app", "prompt": "Hi."},
    )

    assert fake.calls[0][1] == checkout


# --- 8.6 a session started elsewhere ------------------------------------------------------------


def test_a_session_started_in_an_editor_is_listed_with_where_and_what(
    pipeline: Installation, editor: Path, api: httpx.Client, tmp_path: Path
) -> None:
    sessions = listed(api)

    session = sessions[EDITOR_SESSION]
    assert session["runtime"] == "claude_code"
    assert session["cwd"] == str(tmp_path / "project")
    assert "Fix the bug" in session["title"]
    assert set(sessions) >= {EDITOR_SESSION, IDLE_SESSION}


def test_an_idle_claude_session_is_resumed_in_place(
    pipeline: Installation, editor: Path, api: httpx.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = use_claude(monkeypatch, finished_build(editor.parent, "Continued."))

    turn(
        api,
        f"/api/sessions/claude_code/{IDLE_SESSION}/continue",
        {"tab": "t1", "prompt": "And then?"},
    )

    argv = fake.calls[0][0]
    assert argv[argv.index("--resume") + 1] == IDLE_SESSION
    assert "--fork-session" not in argv
    assert "And then?" in prompt_of(argv)


def test_continuing_a_session_a_process_holds_forks_it_instead(
    pipeline: Installation, editor: Path, api: httpx.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = use_claude(monkeypatch, finished_build(editor.parent, "Continued."))
    before = editor.read_bytes()

    with holding_process(EDITOR_SESSION):
        turn(
            api,
            f"/api/sessions/claude_code/{EDITOR_SESSION}/continue",
            {"tab": "t1", "prompt": "And then?"},
        )

    assert "--fork-session" in fake.calls[0][0]
    assert editor.read_bytes() == before


def recorded_acp_session(installation: Installation, session: str) -> None:
    """What a build run recorded of an ACP session, which is how the page knows of it."""
    step = Transcript(
        transcript_dir(installation.state_dir),
        unit("feature/2", change="feature"),
        node="implement",
        round=0,
        started=datetime(2026, 10, 1, 9, 0, 0, tzinfo=UTC),
        result_limit=1000,
        runs_kept=3,
    )
    step.record(TranscriptEvent(kind="text", session=session, text=EARLIER_TURN))
    step.record(TranscriptEvent(kind="stop", session=session, text="end_turn"))


def test_an_acp_session_the_agent_lists_is_resumed_in_place(
    pipeline: Installation, tmp_path: Path, api: httpx.Client
) -> None:
    unit_worktree(pipeline, "feature/2")
    recorded_acp_session(pipeline, SESSION)
    record = tmp_path / "agent.jsonl"
    use_agent(record, resume=True, list_sessions=True, sessions=(SESSION,))

    assert listed(api)[SESSION]["runtime"] == "acp"
    turn(api, f"/api/sessions/acp/{SESSION}/continue", {"tab": "t1", "prompt": "And then?"})

    [resumed] = requests(record, "session/resume")
    assert resumed["sessionId"] == SESSION
    assert requests(record, "session/new") == []
    [prompted] = requests(record, "session/prompt")
    assert prompted["sessionId"] == SESSION


def test_an_acp_session_the_agent_cannot_load_is_read_only_and_says_how_to_go_on(
    pipeline: Installation, tmp_path: Path, api: httpx.Client
) -> None:
    unit_worktree(pipeline, "feature/2")
    recorded_acp_session(pipeline, OLD_ACP)
    use_agent(tmp_path / "agent.jsonl")

    opened = api.get(f"/api/sessions/acp/{OLD_ACP}").json()

    assert opened["read_only"] is True
    assert EARLIER_TURN in str(opened["events"])
    assert opened["actions"] == ["continue_as_new"]
    assert "new session" in opened["reason"].lower()


def test_continuing_it_starts_a_new_session_seeded_with_the_history(
    pipeline: Installation, tmp_path: Path, api: httpx.Client
) -> None:
    unit_worktree(pipeline, "feature/2")
    recorded_acp_session(pipeline, OLD_ACP)
    record = tmp_path / "agent.jsonl"
    use_agent(record)

    turn(api, f"/api/sessions/acp/{OLD_ACP}/continue", {"tab": "t1", "prompt": "Carry on."})

    assert requests(record, "session/resume") == [], "the old session was never resumed"
    assert len(requests(record, "session/new")) == 1
    [prompted] = requests(record, "session/prompt")
    assert prompted["sessionId"] == SESSION != OLD_ACP
    said = " ".join(block.get("text", "") for block in prompted["prompt"])
    assert EARLIER_TURN in said, "the new session is seeded with the history"
    assert "Carry on." in said


def test_an_acp_session_the_agent_does_not_list_is_read_only_though_it_can_resume(
    pipeline: Installation, tmp_path: Path, api: httpx.Client
) -> None:
    unit_worktree(pipeline, "feature/2")
    recorded_acp_session(pipeline, OLD_ACP)
    use_agent(tmp_path / "agent.jsonl", resume=True, list_sessions=True, sessions=())

    opened = api.get(f"/api/sessions/acp/{OLD_ACP}").json()

    assert opened["read_only"] is True
    assert opened["actions"] == ["continue_as_new"]
    assert "new session" in opened["reason"].lower()


def test_continuing_a_session_the_agent_does_not_list_says_it_became_a_new_one(
    pipeline: Installation, tmp_path: Path, api: httpx.Client
) -> None:
    unit_worktree(pipeline, "feature/2")
    recorded_acp_session(pipeline, OLD_ACP)
    use_agent(tmp_path / "agent.jsonl", resume=True, list_sessions=True, sessions=())

    events = turn(api, f"/api/sessions/acp/{OLD_ACP}/continue", {"tab": "t1", "prompt": "Go on."})

    assert any(e["type"] == "CUSTOM" and e["name"] == "continued_as_new" for e in events)


def test_a_seeded_turns_question_is_kept_under_the_new_session_and_not_the_first(
    pipeline: Installation, tmp_path: Path, api: httpx.Client
) -> None:
    unit_worktree(pipeline, "feature/2")
    recorded_acp_session(pipeline, OLD_ACP)
    use_agent(tmp_path / "agent.jsonl")

    turn(api, f"/api/sessions/acp/{OLD_ACP}/continue", {"tab": "t1", "prompt": "Carry on."})

    assert "Carry on." not in str(api.get(f"/api/sessions/acp/{OLD_ACP}").json()["events"])
    new = api.get(f"/api/sessions/acp/{SESSION}").json()
    assert "Carry on." in str(new["events"])


def test_a_units_recorded_claude_session_continued_from_the_sessions_page_keeps_its_model(
    pipeline: Installation, api: httpx.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    tree = unit_worktree(pipeline, "feature/2")
    assert settings.claude_home is not None
    claude_session_file(settings.claude_home, "recorded-claude", tree)
    record_session(pipeline, "feature/2", "recorded-claude", runtime="claude_code", model="opus")
    fake = use_claude(monkeypatch, finished_build(tree, "Hi."))

    turn(api, "/api/sessions/claude_code/recorded-claude/continue", {"tab": "t1", "prompt": "Hi."})

    argv = fake.calls[0][0]
    assert argv[argv.index("--model") + 1] == "opus"
