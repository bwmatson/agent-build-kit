"""A chat turn may change files in the unit's worktree and never moves the branch: the lease
records the changes, outlives the page, and ends only by a commit or a discard. Which turns
are the builder's (policed) and which are free is decided by the unit's recorded session, not
by the directory the session runs in.

The agent is the `claude` binary faked at its stream-json boundary; the worktree is a real
git worktree, and the fake edits it as an agent would. See `tests/chat_serving.py`.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx
import pytest

from agent_build_kit import runtimes
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.lease import Leases, lease_dir
from agent_build_kit.pipeline.unit_store import Cause, FeedbackSource, UnitStore
from agent_build_kit.pipeline.units import RUNNING
from agent_build_kit.pipeline.workspaces import branch_lock
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime
from agent_build_kit.serve.server import start_server
from tests.attach_driver import changed_files, checked_out, head, leave_lease
from tests.chat_serving import (
    WAIT,
    claude_session_file,
    events_of,
    record_session,
    turn,
    until,
    use_claude,
)
from tests.runtimes.claude_cli import FakeClaude, finished_build
from tests.serving import seed_pipeline

pytestmark = pytest.mark.serial

BUILD_SESSION = "0b7e1d52-9c3a-4f8e-b1d6-2a5c7e9f0d41"
FREE_SESSION = "6d2a8f14-3e5b-4c7a-9f0e-1b8d3c6a2e51"
REVIEW = "/api/units/feature/2"
UNIT = "feature/2"


class EditingClaude(FakeClaude):
    """A `claude` that changes `files` in its working directory before it answers."""

    def __init__(self, stdout: str, files: dict[str, str]) -> None:
        super().__init__(stdout=stdout)
        self.files = files

    def __call__(self, argv, **kwargs):
        cwd = kwargs.get("cwd")
        assert cwd is not None
        for name, text in self.files.items():
            (Path(cwd) / name).write_text(text)
        return super().__call__(argv, **kwargs)


@pytest.fixture
def tree(inst: Installation) -> Path:
    seed_pipeline(inst)
    record_session(inst, UNIT, BUILD_SESSION, runtime="claude_code", model="opus")
    return checked_out(inst, UNIT)


def edits(monkeypatch: pytest.MonkeyPatch, tree: Path, **files: str) -> EditingClaude:
    fake = EditingClaude(finished_build(tree, "Done."), files or {"notes.txt": "a change\n"})
    runtimes.names()
    monkeypatch.setitem(runtimes._REGISTRY, "claude_code", ClaudeCodeRuntime(execute=fake))
    return fake


def hook_command(argv: list[str]) -> str:
    settings = json.loads(argv[argv.index("--settings") + 1])
    return settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]


def attachment(inst: Installation, unit_id: str = UNIT):
    return Leases(lease_dir(inst.state_dir)).attachment(unit_id)


# --- the unit's own session edits and cannot commit --------------------------------------------


def test_a_turn_on_the_units_session_edits_the_worktree_and_leaves_the_branch_where_it_was(
    inst: Installation, tree: Path, api: httpx.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = edits(monkeypatch, tree)
    before = head(tree)

    turn(api, f"{REVIEW}/chat", {"tab": "t1", "prompt": "Add a note."})

    assert (tree / "notes.txt").read_text() == "a change\n"
    assert head(tree) == before
    argv, _ = fake.calls[0]
    command = hook_command(argv)
    assert "--no-commit" in command and "--no-push" in command
    assert "--specs" in command, "the builder's policy"
    recorded = attachment(inst)
    assert recorded is not None
    assert recorded.changed == 1, "the lease is marked as holding one changed file"
    assert "worktree" in recorded.checkouts
    assert (recorded.session, recorded.runtime) == (BUILD_SESSION, "claude_code")
    assert recorded.head == before


def test_the_count_follows_the_files_the_turns_changed(
    inst: Installation, tree: Path, api: httpx.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    edits(monkeypatch, tree, **{"a.txt": "1\n", "b.txt": "2\n", "base.txt": "changed\n"})

    turn(api, f"{REVIEW}/chat", {"tab": "t1", "prompt": "Change three files."})

    recorded = attachment(inst)
    assert recorded is not None and recorded.changed == 3
    assert changed_files(tree) == ["a.txt", "b.txt", "base.txt"]


def test_a_turn_that_changes_nothing_leaves_a_lease_marked_as_holding_nothing(
    inst: Installation, tree: Path, api: httpx.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = use_claude(monkeypatch, finished_build(tree, "Nothing to change."))

    turn(api, f"{REVIEW}/chat", {"tab": "t1", "prompt": "Anything to do?"})

    assert fake.calls
    recorded = attachment(inst)
    assert recorded is not None and recorded.changed == 0
    assert hook_command(fake.calls[0][0]).count("--no-commit") == 1


# --- a free session in the same worktree --------------------------------------------------------


def test_a_free_session_in_the_units_worktree_gets_none_of_the_builders_policy(
    inst: Installation, tree: Path, api: httpx.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agent_build_kit.settings import settings

    assert settings.claude_home is not None
    claude_session_file(settings.claude_home, FREE_SESSION, tree)
    fake = edits(monkeypatch, tree)
    before = head(tree)

    turn(
        api,
        f"/api/sessions/claude_code/{FREE_SESSION}/continue",
        {"tab": "t1", "prompt": "Change the notes."},
    )

    argv, _ = fake.calls[0]
    command = hook_command(argv)
    assert "--no-commit" in command and "--no-push" in command
    assert "--specs" not in command, "not the builder's policy"
    assert "--disallowedTools" not in argv
    assert head(tree) == before
    recorded = attachment(inst)
    assert recorded is not None
    assert (recorded.changed, recorded.session) == (1, FREE_SESSION)


def test_a_session_started_in_the_ui_for_a_unit_is_free_and_refuses_commit_and_push(
    inst: Installation, tree: Path, api: httpx.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = edits(monkeypatch, tree)

    turn(
        api,
        "/api/sessions",
        {"tab": "t1", "runtime": "claude_code", "unit": UNIT, "prompt": "Look around."},
    )

    argv, _ = fake.calls[0]
    command = hook_command(argv)
    assert "--no-commit" in command and "--no-push" in command
    assert "--specs" not in command
    assert "--disallowedTools" not in argv


# --- the lease outlives the page and ends by a commit or a discard -----------------------------


def test_closing_the_page_keeps_a_lease_that_holds_changes(
    inst: Installation, tree: Path, api: httpx.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    edits(monkeypatch, tree)
    with api.stream("GET", f"{REVIEW}/agent/events", params={"tab": "t1"}, timeout=WAIT) as page:
        page_events = events_of(page)  # kept: dropping the iterator would close the stream
        next(page_events)
        turn(api, f"{REVIEW}/chat", {"tab": "t1", "prompt": "Add a note."})
        assert attachment(inst) is not None

    time.sleep(0.6)  # long enough for the server to see the page go

    kept = attachment(inst)
    assert kept is not None and kept.changed == 1
    assert (tree / "notes.txt").exists()


def test_closing_the_page_releases_a_lease_that_holds_nothing(
    inst: Installation, tree: Path, api: httpx.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = use_claude(monkeypatch, finished_build(tree, "Nothing to change."))
    with api.stream("GET", f"{REVIEW}/agent/events", params={"tab": "t1"}, timeout=WAIT) as page:
        page_events = events_of(page)
        next(page_events)
        turn(api, f"{REVIEW}/chat", {"tab": "t1", "prompt": "Anything to do?"})
        assert attachment(inst) is not None

    assert until(lambda: attachment(inst) is None)
    assert "--no-commit" in hook_command(fake.calls[0][0])


def test_releasing_a_lease_with_changes_is_refused_and_offers_commit_and_discard(
    inst: Installation, tree: Path, api: httpx.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    edits(monkeypatch, tree)
    turn(api, f"{REVIEW}/chat", {"tab": "t1", "prompt": "Add a note."})

    released = api.delete(f"{REVIEW}/lease", params={"tab": "t1"})

    assert released.status_code == 409
    assert "discard" in released.text.lower() and "commit" in released.text.lower()
    assert attachment(inst) is not None
    assert (tree / "notes.txt").exists()


# --- discard ------------------------------------------------------------------------------------


def test_discard_lists_the_files_that_would_be_lost(
    inst: Installation, tree: Path, api: httpx.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    edits(monkeypatch, tree, **{"notes.txt": "a change\n", "base.txt": "changed\n"})
    turn(api, f"{REVIEW}/chat", {"tab": "t1", "prompt": "Change two files."})

    listed = api.get(f"{REVIEW}/changes", params={"tab": "t1"})

    assert listed.status_code == 200
    assert sorted(listed.json()["files"]) == ["base.txt", "notes.txt"]
    assert changed_files(tree) == ["base.txt", "notes.txt"], "listing changes nothing"


def test_discard_without_a_confirmation_changes_nothing(
    inst: Installation, tree: Path, api: httpx.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    edits(monkeypatch, tree)
    turn(api, f"{REVIEW}/chat", {"tab": "t1", "prompt": "Add a note."})

    refused = api.post(f"{REVIEW}/discard", json={"tab": "t1"})

    assert refused.status_code in (400, 409, 422)
    assert (tree / "notes.txt").exists()
    assert attachment(inst) is not None


def test_a_confirmed_discard_restores_the_tree_and_releases_the_lease_in_one_request(
    inst: Installation, tree: Path, api: httpx.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    edits(monkeypatch, tree, **{"notes.txt": "a change\n", "base.txt": "changed\n"})
    before = head(tree)
    turn(api, f"{REVIEW}/chat", {"tab": "t1", "prompt": "Change two files."})

    discarded = api.post(f"{REVIEW}/discard", json={"tab": "t1", "confirmed": True})

    assert discarded.status_code == 200
    assert head(tree) == before
    assert changed_files(tree) == []
    assert (tree / "base.txt").read_text() == "base\n"
    assert attachment(inst) is None


# --- which units a chat attaches to -------------------------------------------------------------


def test_only_a_unit_in_a_stable_state_accepts_a_chat(
    inst: Installation, tree: Path, api: httpx.Client
) -> None:
    for held_unit in ("feature/5", "feature/6"):
        record_session(inst, held_unit, BUILD_SESSION, runtime="claude_code")
    record_session(inst, "feature/7", FREE_SESSION, runtime="claude_code")
    store = UnitStore(inst.state_dir / "units.json")
    # Paused for the usage window part-way through a rework of a review's comments.
    store.set_feedback("feature/7", "rename it", source=FeedbackSource.REVIEW)
    store.set_state("feature/7", RUNNING, note="waiting out the usage window", cause=Cause.USAGE)

    def composer(unit: str) -> dict:
        return api.get(f"/api/units/{unit}/agent", params={"tab": "t1"}).json()["composer"]

    assert composer("feature/2")["enabled"] is True, "in review"
    assert composer("feature/5")["enabled"] is True, "held"
    assert composer("feature/6")["enabled"] is True, "failed"
    paused = composer("feature/7")
    assert paused["enabled"] is False
    assert "paused" in paused["reason"].lower()
    assert "step is running" not in paused["reason"].lower()

    reply = api.post("/api/units/feature/7/chat", json={"tab": "t1", "prompt": "Go on."})

    assert reply.status_code == 409
    assert Leases(lease_dir(inst.state_dir)).attachment("feature/7") is None, "no lease left"


# --- the server takes over what a server left ---------------------------------------------------


def test_a_server_that_starts_takes_over_a_stale_lease_with_changes(
    inst: Installation, tree: Path
) -> None:
    (tree / "notes.txt").write_text("left by a chat\n")
    leave_lease(lease_dir(inst.state_dir), UNIT, files=1)
    stale = attachment(inst)
    assert stale is not None and stale.stale is True

    with start_server(inst):
        taken = attachment(inst)

    assert taken is not None
    assert (taken.stale, taken.changed) == (False, 1)
    assert (tree / "notes.txt").read_text() == "left by a chat\n", "nothing was touched"


def test_a_restarted_server_lets_a_fresh_page_discard_what_it_took_over(
    inst: Installation, tree: Path
) -> None:
    (tree / "notes.txt").write_text("left by a chat\n")
    leave_lease(lease_dir(inst.state_dir), UNIT, files=1)

    with start_server(inst) as server, httpx.Client(base_url=server.url) as api:
        refused = api.delete(f"{REVIEW}/lease", params={"tab": "fresh"})
        discarded = api.post(f"{REVIEW}/discard", json={"tab": "fresh", "confirmed": True})

    assert refused.status_code == 409, "a lease with changes is not released"
    assert discarded.status_code == 200
    assert changed_files(tree) == []
    assert attachment(inst) is None


# --- discard never runs under a step ------------------------------------------------------------


def test_discard_is_refused_while_a_step_holds_the_units_branch(
    inst: Installation, tree: Path, api: httpx.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    edits(monkeypatch, tree)
    turn(api, f"{REVIEW}/chat", {"tab": "t1", "prompt": "Add a note."})

    with branch_lock("spec/feature/2", root=inst.state_dir / "locks"):
        refused = api.post(f"{REVIEW}/discard", json={"tab": "t1", "confirmed": True})

    assert refused.status_code == 409
    assert "step is running" in refused.text
    assert (tree / "notes.txt").exists(), "the running agent's work is where it was"
    kept = attachment(inst)
    assert kept is not None and kept.changed == 1


def test_discard_with_nothing_attached_is_refused(
    inst: Installation, tree: Path, api: httpx.Client
) -> None:
    (tree / "notes.txt").write_text("by hand\n")

    refused = api.post(f"{REVIEW}/discard", json={"tab": "t1", "confirmed": True})

    assert refused.status_code == 409
    assert (tree / "notes.txt").exists()
