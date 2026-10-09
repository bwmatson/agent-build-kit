"""A free session (one that is not the unit's build session) is given no pipeline guidance and no
constraint on what it edits: it changes a source file in the unit's worktree and a change's task
file in the planning checkout in one session, both stay uncommitted and are recorded on its lease,
and the turns the server runs refuse `git commit` and `git push`.

The agent is the `claude` binary faked at its stream-json boundary; the unit's worktree and the
planning checkout are real git repositories. The server runs the policy hook as a command from
the turn's `--settings`, so the test runs that command on the payloads Claude Code sends it.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import httpx
import pytest

from agent_build_kit import runtimes
from agent_build_kit.installation import Installation
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime
from tests.attach_driver import changed_files, checked_out, head
from tests.chat_serving import claude_session_file, prompt_of, record_session, turn
from tests.factories import git, init_repo
from tests.runtimes.claude_cli import FakeClaude, finished_build
from tests.serving import seed_pipeline

pytestmark = pytest.mark.serial

BUILD_SESSION = "0b7e1d52-9c3a-4f8e-b1d6-2a5c7e9f0d71"
FREE_SESSION = "6d2a8f14-3e5b-4c7a-9f0e-1b8d3c6a2e71"
UNIT = "feature/2"
TASKS = (
    "# Tasks\n\n## 1. [app] [tier1] A group\n\n- [ ] 1.1 Test: it works\n"
    "\n## 2. [app] [tier1] Another group\n\n- [ ] 2.1 Test: it also works\n"
)
EDITED_TASKS = TASKS.replace("Another group", "Another group, reworded")


class EditsBoth(FakeClaude):
    """A `claude` that edits a source file in its working directory and the change's task file,
    given by absolute path, as an agent that was asked to change code and spec together does."""

    def __init__(self, stdout: str, tasks: Path) -> None:
        super().__init__(stdout=stdout)
        self.tasks = tasks

    def __call__(self, argv, **kwargs):  # type: ignore[no-untyped-def]
        cwd = kwargs.get("cwd")
        assert cwd is not None
        (Path(cwd) / "notes.py").write_text("NOTE = 1\n")
        self.tasks.write_text(EDITED_TASKS)
        return super().__call__(argv, **kwargs)


def hook_of(argv: list[str]) -> str:
    settings = json.loads(argv[argv.index("--settings") + 1])
    return settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]


def asked(command: str, payload: dict[str, object]) -> str:
    """What the policy hook prints for `payload`: a deny decision, or nothing."""
    done = subprocess.run(
        command, shell=True, input=json.dumps(payload), capture_output=True, text=True
    )
    return done.stdout


@pytest.fixture
def planning(inst: Installation) -> Path:
    """The planning checkout, a repository holding the change's task file."""
    repo = init_repo(inst.root)
    (repo / ".gitignore").write_text("runs/\nabk.yaml\n")
    tasks = inst.changes_dir / "feature" / "tasks.md"
    tasks.parent.mkdir(parents=True)
    tasks.write_text(TASKS)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "plan")
    return repo


@pytest.fixture
def tree(inst: Installation) -> Path:
    seed_pipeline(inst)
    record_session(inst, UNIT, BUILD_SESSION, runtime="claude_code", model="opus")
    return checked_out(inst, UNIT)


def test_a_free_session_changes_code_and_a_task_file_in_one_session_and_commits_neither(
    inst: Installation,
    tree: Path,
    planning: Path,
    api: httpx.Client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent_build_kit.pipeline.lease import Leases, lease_dir
    from agent_build_kit.settings import settings

    assert settings.claude_home is not None
    claude_session_file(settings.claude_home, FREE_SESSION, tree)
    tasks = inst.changes_dir / "feature" / "tasks.md"
    fake = EditsBoth(finished_build(tree, "Done."), tasks)
    runtimes.names()
    monkeypatch.setitem(runtimes._REGISTRY, "claude_code", ClaudeCodeRuntime(execute=fake))
    worktree_head, planning_head = head(tree), head(planning)

    turn(
        api,
        f"/api/sessions/claude_code/{FREE_SESSION}/continue",
        {"tab": "t1", "prompt": "Change the notes and the task wording."},
    )

    argv, _ = fake.calls[0]
    assert prompt_of(argv) == "Change the notes and the task wording.", "no guidance is added"
    assert "--append-system-prompt" not in argv
    command = hook_of(argv)
    assert "--specs" not in command and "--disallowedTools" not in argv, "no constraint"
    assert changed_files(tree) == ["notes.py"]
    assert changed_files(planning) == ["openspec/changes/feature/tasks.md"]
    assert (head(tree), head(planning)) == (worktree_head, planning_head), "nothing committed"

    held = Leases(lease_dir(inst.state_dir)).attachment(UNIT)
    assert held is not None
    assert set(held.checkouts) == {"worktree", "planning"}, "the lease covers both checkouts"
    assert held.changed == 2, "one changed file in each"

    # What the hook says to the tool calls the agent made: the edits are not objected to, and
    # the commit and push it never made are refused.
    edit_source = {"tool_name": "Edit", "tool_input": {"file_path": str(tree / "notes.py")}}
    edit_tasks = {"tool_name": "Edit", "tool_input": {"file_path": str(tasks)}}
    assert asked(command, {**edit_source, "cwd": str(tree)}) == ""
    assert asked(command, {**edit_tasks, "cwd": str(tree)}) == ""
    for refused in ("git commit -am wip", "git push origin HEAD"):
        bash: dict[str, object] = {
            "tool_name": "Bash",
            "tool_input": {"command": refused},
            "cwd": str(tree),
        }
        assert "deny" in asked(command, bash), refused
