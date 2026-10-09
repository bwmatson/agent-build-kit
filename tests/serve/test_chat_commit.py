"""Committing a chat's changes is one request: it commits through the repo's hooks, with the
unit's agent fixing what they reject, releases the lease and delivers the `adopted` event, and
answers with the commit, the unit's state and whether the delivery completed. A commit made and
not delivered is finished once, by the next server start or by repeating the request.

    POST /api/units/{change}/{number}/commit   {"tab", "message", "commit"?, "checkouts"?}
         200 {"commit": SHA, "state": STATE, "delivered": bool}
         409 the hooks rejected the commit after the bounded fix loop; the detail holds their
             output, and the lease and the changes are kept

The agent is the `claude` binary faked at its stream-json boundary, as in `test_chat_editing.py`;
the worktree, its hooks and the checkpointed thread are real.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from agent_build_kit import config as config_module
from agent_build_kit import runtimes
from agent_build_kit.config import OpenSpecConfig
from agent_build_kit.graph.checkpointer import open_checkpointer, unit_graphs_path
from agent_build_kit.graph.state import Node
from agent_build_kit.graph.unit import thread_position
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.lease import Leases, lease_dir
from agent_build_kit.pipeline.outside_commits import outside_commits
from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import RUNNING
from agent_build_kit.pipeline.wiring import COMMIT_FIX_ROUNDS
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime
from agent_build_kit.serve.server import start_server
from tests.attach_driver import changed_files, checked_out, head, leave_lease
from tests.chat_serving import prompt_of, record_session, turn
from tests.factories import git, init_repo
from tests.runtimes.claude_cli import FakeClaude, finished_build
from tests.serving import seed_pipeline

pytestmark = pytest.mark.serial

BUILD_SESSION = "0b7e1d52-9c3a-4f8e-b1d6-2a5c7e9f0d41"
REVIEW = "/api/units/feature/2"
UNIT = "feature/2"


class ScriptedClaude(FakeClaude):
    """A `claude` that writes the next entry of `scripts` into its working directory before it
    answers, the last entry again once they are spent."""

    def __init__(self, stdout: str, *scripts: dict[str, str]) -> None:
        super().__init__(stdout=stdout)
        self.scripts = list(scripts)

    def __call__(self, argv, **kwargs):
        cwd = kwargs.get("cwd")
        assert cwd is not None
        script = self.scripts[min(len(self.calls), len(self.scripts) - 1)]
        for name, text in script.items():
            (Path(cwd) / name).write_text(text)
        return super().__call__(argv, **kwargs)


@pytest.fixture
def tree(inst: Installation) -> Path:
    seed_pipeline(inst)
    record_session(inst, UNIT, BUILD_SESSION, runtime="claude_code", model="opus")
    return checked_out(inst, UNIT)


def scripted(monkeypatch: pytest.MonkeyPatch, tree: Path, *scripts: dict[str, str]):
    fake = ScriptedClaude(finished_build(tree, "Done."), *scripts)
    runtimes.names()
    monkeypatch.setitem(runtimes._REGISTRY, "claude_code", ClaudeCodeRuntime(execute=fake))
    return fake


def pre_commit(tree: Path, script: str) -> None:
    common = git(tree, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
    hooks = Path(common) / "hooks"
    hooks.mkdir(exist_ok=True)
    hook = hooks / "pre-commit"
    hook.write_text("#!/bin/sh\n" + script)
    hook.chmod(0o755)


def attachment(inst: Installation, unit_id: str = UNIT):
    return Leases(lease_dir(inst.state_dir)).attachment(unit_id)


def waiting_at(inst: Installation, unit_id: str = UNIT) -> tuple[str, ...]:
    async def read() -> tuple[str, ...]:
        async with open_checkpointer(unit_graphs_path(inst.state_dir)) as saver:
            return tuple((await thread_position(saver, unit_id)).next)

    return asyncio.run(read())


def adoptions(inst: Installation, unit_id: str = UNIT) -> int:
    history = UnitStore(inst.state_dir / "units.json").history(unit_id)
    return sum(1 for entry in history if entry.get("cause") == Cause.ADOPTED.value)


def commit(api: httpx.Client, **body: object) -> httpx.Response:
    return api.post(f"{REVIEW}/commit", json={"tab": "t1", "message": "Add a note", **body})


def chat_edit(api: httpx.Client) -> None:
    turn(api, f"{REVIEW}/chat", {"tab": "t1", "prompt": "Add a note."})


# --- one request commits, releases and delivers -------------------------------------------------


def test_one_request_commits_releases_and_hands_the_unit_to_its_checks(
    inst: Installation, tree: Path, api: httpx.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    scripted(monkeypatch, tree, {"notes.txt": "a change\n"})
    chat_edit(api)
    before = head(tree)
    assert waiting_at(inst) == (Node.AWAIT_REVIEW,)

    answer = commit(api)

    assert answer.status_code == 200
    made = head(tree)
    assert made != before
    assert git(tree, "rev-parse", "HEAD~1").strip() == before
    assert answer.json() == {"commit": made, "state": RUNNING, "delivered": True}
    assert changed_files(tree) == []
    assert attachment(inst) is None, "released in the same request"
    assert waiting_at(inst) == (Node.CHECKS,), "the adopted event entered at the checks"
    assert adoptions(inst) == 1
    message = git(tree, "log", "-1", "--format=%B")
    assert message.splitlines()[0] == "Add a note"
    assert f"Unit: {UNIT}" in message
    assert f"Adopted-From: {BUILD_SESSION}" in message


def test_a_free_sessions_commit_carries_its_own_session_and_is_outside_the_builders(
    inst: Installation, tree: Path, api: httpx.Client
) -> None:
    free = "6d2a8f14-3e5b-4c7a-9f0e-1b8d3c6a2e41"
    leases = Leases(lease_dir(inst.state_dir))
    assert leases.take(
        UNIT, "tab:t1", checkouts=("worktree",), session=free, runtime="claude_code", head="abc"
    )
    (tree / "notes.txt").write_text("by a free session\n")
    before = head(tree)

    answer = commit(api, checkouts=["worktree"])

    assert answer.status_code == 200
    message = git(tree, "log", "-1", "--format=%B")
    assert f"Adopted-From: {free}" in message
    assert BUILD_SESSION not in message
    [outside] = outside_commits(tree, before, BUILD_SESSION)
    assert (outside.commit, outside.session) == (head(tree), free)


# --- the hooks ----------------------------------------------------------------------------------


def test_a_hook_that_reformats_the_files_is_retried_and_the_commit_succeeds(
    inst: Installation, tree: Path, api: httpx.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = scripted(monkeypatch, tree, {"notes.txt": "a   change\n"})
    chat_edit(api)
    marker = tree.parent / "formatted-once"
    pre_commit(
        tree,
        f'if [ ! -f "{marker}" ]; then touch "{marker}"; printf "a change\\n" > notes.txt; '
        'echo "reformatted notes.txt" >&2; exit 1; fi\nexit 0\n',
    )

    answer = commit(api)

    assert answer.status_code == 200 and answer.json()["delivered"] is True
    assert git(tree, "show", "HEAD:notes.txt") == "a change", "the committed file is formatted"
    assert len(fake.calls) == 1, "the agent was not asked: the retry was enough"


def test_a_hook_the_agent_must_fix_is_given_to_the_agent_and_the_commit_tried_again(
    inst: Installation, tree: Path, api: httpx.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = scripted(monkeypatch, tree, {"notes.txt": "BAD word\n"}, {"notes.txt": "fine\n"})
    chat_edit(api)
    pre_commit(
        tree,
        'if grep -q BAD notes.txt; then echo "lint: BAD word in notes.txt" >&2; exit 1; fi\n'
        "exit 0\n",
    )
    before = head(tree)

    answer = commit(api)

    assert answer.status_code == 200 and answer.json()["delivered"] is True
    assert len(fake.calls) == 2, "the turn, then the fix"
    argv, cwd = fake.calls[1]
    assert "lint: BAD word in notes.txt" in prompt_of(argv), "the hook's own output"
    assert cwd is not None and Path(cwd).resolve() == tree.resolve()
    assert BUILD_SESSION in argv, "the unit's own session fixes it"
    assert git(tree, "show", "HEAD:notes.txt") == "fine"
    assert head(tree) != before
    assert attachment(inst) is None
    kept = " ".join(
        path.read_text()
        for path in sorted((inst.state_dir / "transcripts").rglob("*commit*.jsonl"))
    )
    assert "lint: BAD word in notes.txt" in kept, "the fix turn is in the unit's transcript"
    assert kept.index('"kind":"user"') < kept.index('"kind":"stop"'), "the turn ran to its stop"


def test_a_commit_still_rejected_after_the_bound_is_a_conflict_that_keeps_everything(
    inst: Installation, tree: Path, api: httpx.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = scripted(monkeypatch, tree, {"notes.txt": "a change\n"})
    chat_edit(api)
    pre_commit(tree, 'echo "lint: no way" >&2\nexit 1\n')
    before = head(tree)
    asked = len(fake.calls)

    answer = commit(api)

    assert answer.status_code == 409
    assert "lint: no way" in answer.text, "the hook output"
    assert len(fake.calls) - asked == COMMIT_FIX_ROUNDS, "the helper's bound"
    assert head(tree) == before
    assert "notes.txt" in git(tree, "status", "--porcelain"), "the changes stay uncommitted"
    kept = attachment(inst)
    assert kept is not None and kept.changed == 1 and not kept.stale
    assert waiting_at(inst) == (Node.AWAIT_REVIEW,), "nothing was delivered"
    assert adoptions(inst) == 0


def test_a_commit_with_nothing_to_commit_is_a_conflict_that_changes_nothing(
    inst: Installation, tree: Path, api: httpx.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    scripted(monkeypatch, tree, {})
    chat_edit(api)
    before = head(tree)

    answer = commit(api)

    assert answer.status_code == 409
    assert "nothing to commit" in answer.text
    assert head(tree) == before
    kept = attachment(inst)
    assert kept is not None and not kept.committed, "the lease is kept"
    assert waiting_at(inst) == (Node.AWAIT_REVIEW,)
    assert adoptions(inst) == 0


# --- a commit made and not delivered ------------------------------------------------------------


def undelivered(inst: Installation, tree: Path) -> str:
    """A commit the server made and stopped before delivering: the lease carries its hash."""
    (tree / "notes.txt").write_text("a change\n")
    git(tree, "add", "-A")
    git(tree, "commit", "-q", "-m", "Add a note")
    made = head(tree)
    leave_lease(lease_dir(inst.state_dir), UNIT, commit=made)
    marked = attachment(inst)
    assert marked is not None and (marked.stale, marked.committed) == (True, made)
    return made


def test_a_server_that_starts_finishes_the_delivery_of_a_commit_once(
    inst: Installation, tree: Path
) -> None:
    undelivered(inst, tree)

    with start_server(inst):
        assert attachment(inst) is None, "the record is removed"
    with start_server(inst):
        pass

    assert waiting_at(inst) == (Node.CHECKS,)
    assert adoptions(inst) == 1, "delivered once, not again by the next start"


def test_repeating_the_request_with_the_same_commit_delivers_nothing_again(
    inst: Installation, tree: Path, api: httpx.Client
) -> None:
    made = undelivered(inst, tree)

    first = commit(api, commit=made)
    again = commit(api, commit=made)

    assert first.status_code == again.status_code == 200
    assert first.json() == again.json() == {"commit": made, "state": RUNNING, "delivered": True}
    assert adoptions(inst) == 1
    assert attachment(inst) is None
    assert head(tree) == made, "no second commit"


# --- the planning checkout ----------------------------------------------------------------------


def test_a_commit_of_the_planning_checkout_releases_its_part_and_sends_the_unit_nothing(
    inst: Installation, tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The planning gate passes: OpenSpec, faked at its process boundary, finds nothing wrong,
    # and the change's tasks are tagged.
    openspec = inst.root.parent / "fake-openspec"
    openspec.write_text("#!/bin/sh\necho '[]'\n")
    openspec.chmod(0o755)
    current = config_module.active()
    config_module.activate(
        current.model_copy(update={"openspec": OpenSpecConfig(command=[str(openspec)])}),
        config_module.active_root(),
    )
    tasks = inst.changes_dir / "feature" / "tasks.md"
    tasks.parent.mkdir(parents=True)
    tasks.write_text(
        "# Tasks\n\n## 1. [app] [tier1] A group\n\nAcceptance: none — nothing to drive\n\n"
        "- [ ] 1.1 Test: it works\n"
    )
    planning = init_repo(inst.root)
    (planning / ".gitignore").write_text("runs/\n")  # the pipeline's state is not a plan
    (planning / "notes.md").write_text("start\n")
    git(planning, "add", "-A")
    git(planning, "commit", "-q", "-m", "start")
    (planning / "notes.md").write_text("a chat's plan\n")
    (tree / "notes.txt").write_text("a change\n")
    leave_lease(lease_dir(inst.state_dir), UNIT, files=1, checkouts=("worktree", "planning"))

    with start_server(inst) as server, httpx.Client(base_url=server.url) as api:
        answer = commit(api, message="Plan the note", checkouts=["planning"])

    assert answer.status_code == 200
    assert git(planning, "log", "-1", "--format=%s").strip() == "Plan the note"
    assert git(planning, "status", "--porcelain").strip() == ""
    kept = attachment(inst)
    assert kept is not None and kept.checkouts == ("worktree",), "that part is released"
    assert changed_files(tree) == ["notes.txt"], "the worktree's changes are untouched"
    assert waiting_at(inst) == (Node.AWAIT_REVIEW,)
    assert adoptions(inst) == 0, "no unit is sent anything"
