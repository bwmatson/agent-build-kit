"""Editing from chat over a real scratch installation: a chat edit to a reviewed commit.

The agent is a real Claude Code on this host, reached through a recorder: a wrapper script set as
`runtimes.claude_code.command` that copies its standard input (where the prompt is sent) into a
file and then `exec`s `claude`, so what the pipeline told it is read at the process boundary and
no process of the wrapper's own is left. The scratch installation is built for the runtime a
fixture parameter names, so the same scenarios can run on another runtime from a module that
imports this one. `abk tick` and `abk attach release` are the real CLI run as processes, and the
server is the real one, serving the scratch installation in this process and driven over HTTP as the
page drives it. Only GitHub is faked, as in the other acceptance runs.

What is asserted is what an operator sees:

- a build-session chat edits a test and its code without committing; a pre-commit hook that rejects
  the commit is satisfied by the agent; the one commit request commits, releases the lease and
  delivers the unit to its review, which takes no place in the round limit and adds no
  outside-commit part to any prompt;
- a request against a requirement is answered with a flag and changes no file;
- a free session changes code and a change's task file together, both are committed (each checkout
  on its own) and the unit's next rework is told of the outside commit;
- a stale attachment is released from the command line.

Needs Claude Code, node for the OpenSpec CLI and uv. Bills on demand and takes
minutes, so it is marked e2e-test and excluded from the default suite.
"""

from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
import sys
import textwrap
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import Field

from agent_build_kit import config
from agent_build_kit.graph.checkpointer import open_checkpointer, unit_graphs_path
from agent_build_kit.graph.state import SessionRole
from agent_build_kit.graph.unit import thread_position
from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.lease import Leases, lease_dir
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.workspaces import worktree_path
from agent_build_kit.serve.server import start_server
from tests.attach_driver import leave_lease
from tests.factories import git, init_repo, scratch_app
from tests.forges.github_server import FakeGitHub
from tests.forges.process_host import process_env
from tests.runtime_scratch import CLAUDE_CODE_PARAMS, runtime_scratch
from tests.scratch_tick import commits_on_unit_branch, run_tick

pytestmark = [
    pytest.mark.local_stack,
    pytest.mark.skipif(shutil.which("npx") is None, reason="npx is not on PATH"),
    pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not on PATH"),
]

CHANGE = "add-marker"
BRANCH = f"spec/{CHANGE}/1"
UNIT_ID = f"{CHANGE}/1"
UNIT_URL = f"/api/units/{CHANGE}/1"
HOOK_MARKER = "FIXME-CHAT"
OUTSIDE_NOTE = "Commits made outside this session"
CHAT_COMMIT_REVIEW = "review of a chat's commit"
COMMENT = "Please also say in the docstring of `marker()` that it is a marker."

TASKS = """# Tasks

## 1. [app] [unit-test] Add the marker

- [ ] 1.1 Test: `marker()` in `src/app/marker.py` returns the string `"marked"`.
- [ ] 1.2 Add `marker()` to `src/app/marker.py`.

Acceptance: none — a single function whose own test is its proof
"""

# Claude Code's recorder: the prompt arrives on standard input, which is copied to the prompts file
# and handed on from a file the shell has already unlinked, so `exec` leaves Claude, with its own
# arguments (and the session id among them), as the only process. A call given no input, with
# standard input a terminal, is not read, so it does not wait for one.
CLAUDE_RECORDER = """#!/bin/sh
[ -t 0 ] && exec claude "$@"
tmp=$(mktemp)
cat > "$tmp"
cat "$tmp" >> "{prompts}"
exec 3< "$tmp"
rm -f "$tmp"
exec claude "$@" <&3
"""

# The protocol runtime's recorder: each line the client sends the agent is appended to a file.
RECORDER = textwrap.dedent(
    """\
    import subprocess, sys, threading

    log, command = sys.argv[1], sys.argv[2:]
    child = subprocess.Popen(command, stdin=subprocess.PIPE)

    def copy() -> None:
        assert child.stdin is not None
        with open(log, "ab") as record:
            for line in sys.stdin.buffer:
                record.write(line)
                record.flush()
                child.stdin.write(line)
                child.stdin.flush()
        child.stdin.close()

    threading.Thread(target=copy, daemon=True).start()
    sys.exit(child.wait())
    """
)

# A hook the agent has to satisfy: the commit is rejected while a file carries the marker.
HOOK = f"""#!/bin/sh
echo run >> "$(git rev-parse --git-common-dir)/hook-runs"
if git diff --cached | grep -q '^+.*{HOOK_MARKER}'; then
  echo "{HOOK_MARKER} markers are not allowed in a commit: remove the line that holds one" >&2
  exit 1
fi
"""


class Ran(Frozen):
    returncode: int
    output: str


class Scratch(Frozen):
    model_config = {"arbitrary_types_allowed": True}

    planning: Path
    app: Path
    remote: Path
    runtime: str
    installation: Installation
    state: Path
    prompts: Path
    host: FakeGitHub
    env: dict[str, str] = Field(repr=False)

    @property
    def tree(self) -> Path:
        unit = UnitStore(self.installation.state_dir / "units.json").get(UNIT_ID)
        assert unit.branch
        return worktree_path(
            self.installation.checkouts[unit.repo], unit.branch, self.installation.worktree_root
        )


@pytest.fixture(scope="module")
def github_host() -> Iterator[FakeGitHub]:
    """The fake host, numbering its first pull request 7."""
    with FakeGitHub(first_number=7) as server:
        yield server
        missed = server.unrouted()
        assert missed == [], f"the forge called routes the fake host does not serve: {missed}"


def recorded_runtimes(runtime: str, prompts: Path, command: list[str], directory: Path) -> str:
    """The `runtimes` section of `abk.yaml` that wraps the agent of `runtime` in its recorder."""
    if runtime == "acp":
        recorder = directory / "recorder.py"
        recorder.write_text(RECORDER)
        wrapped = [sys.executable, str(recorder), str(prompts), *command]
    else:
        recorder = directory / "claude-recorder.sh"
        recorder.write_text(CLAUDE_RECORDER.format(prompts=prompts))
        recorder.chmod(0o755)
        wrapped = [str(recorder)]
    return f"runtimes:\n  {runtime}:\n    command: {wrapped}\n"


@pytest.fixture(scope="module", params=CLAUDE_CODE_PARAMS)
def scratch(
    request: pytest.FixtureRequest,
    tmp_path_factory: pytest.TempPathFactory,
    github_host: FakeGitHub,
) -> Scratch:
    """The scratch installation for the runtime the test is parametrized with."""
    tmp_path = tmp_path_factory.mktemp("chat-editing")
    runtime = runtime_scratch(request.param, tmp_path_factory, lambda command: None)
    prompts = tmp_path / "prompts.log"

    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    app = scratch_app(tmp_path / "app")
    git(app, "remote", "add", "origin", str(remote))
    git(app, "push", "-q", "origin", "main")

    planning = init_repo(tmp_path / "planning")
    change = planning / "openspec" / "changes" / CHANGE
    (change / "specs" / "marker").mkdir(parents=True)
    (planning / "openspec" / "config.yaml").write_text("schema: spec-driven\n")
    (change / "proposal.md").write_text(
        "## Why\n\nThe app needs a marker.\n\n## What Changes\n\n- Add `marker()`.\n\n"
        "## Impact\n\n- app: one module.\n"
    )
    (change / "specs" / "marker" / "spec.md").write_text(
        "## ADDED Requirements\n\n### Requirement: A marker\nThe app SHALL expose `marker()`.\n\n"
        "#### Scenario: Reading it\n- **WHEN** `marker()` is called\n"
        '- **THEN** it returns "marked"\n'
    )
    (change / "tasks.md").write_text(TASKS)
    (planning / "abk.yaml").write_text(
        f"repos:\n  app:\n    path: {app}\n    slug: example/app\n"
        "    profile: python-uv\n    languages: [python]\n"
        f"planning:\n  worktree_root: {tmp_path / 'worktrees'}\n"
        f"{recorded_runtimes(runtime.runtime, prompts, runtime.command, tmp_path)}"
    )
    (planning / ".gitignore").write_text("runs/\n")
    git(planning, "add", "-A")
    git(planning, "commit", "-q", "-m", "plan")

    env = {
        **process_env(github_host, tmp_path / "bin", tmp_path / "gh-calls.txt"),
        **runtime.env,
        "ABK_CONFIG": str(planning / "abk.yaml"),
        "ABK_WORKTREE_ROOT": str(tmp_path / "worktrees"),
    }
    installation = Installation(config.load(planning / "abk.yaml"), planning)
    return Scratch(
        runtime=runtime.runtime,
        planning=planning,
        app=app,
        remote=remote,
        installation=installation,
        state=installation.state_dir,
        prompts=prompts,
        host=github_host,
        env=env,
    )


@pytest.fixture(autouse=True)
def scratch_workspace(workspace: object, scratch: Scratch) -> Iterator[None]:
    """The scratch installation is the active one for each test, after the suite's default
    workspace: the server thread reads its runtime command and repos from it. Whatever a
    failed test left behind, a lease held by this process and uncommitted files, is cleared
    after it, so the one failure is not followed by a conflict in every later test."""
    scratch.installation.activate()
    yield
    Leases(lease_dir(scratch.installation.state_dir)).drop(UNIT_ID)
    try:
        tree = scratch.tree
    except Exception:  # the unit was never built: nothing to clean
        return
    if tree.is_dir():
        git(tree, "reset", "-q", "--hard", "HEAD")
        git(tree, "clean", "-qfd")


@pytest.fixture(scope="module")
def api(scratch: Scratch) -> Iterator[httpx.Client]:
    with (
        start_server(scratch.installation, agent_environment=scratch.env) as server,
        httpx.Client(base_url=server.url, timeout=1800) as client,
    ):
        yield client


def abk(scratch: Scratch, *args: str) -> Ran:
    run = subprocess.run(
        [str(Path(sys.executable).parent / "abk"), *args],
        cwd=scratch.planning,
        env=scratch.env,
        capture_output=True,
        text=True,
        timeout=3600,
    )
    return Ran(returncode=run.returncode, output=run.stdout + run.stderr)


def run_log(scratch: Scratch) -> str:
    logs = sorted((scratch.installation.state_dir / "unit-logs").glob(f"{CHANGE}-01-*.log"))
    return "\n".join(path.read_text() for path in logs)


def log_names(scratch: Scratch) -> set[str]:
    return {
        path.name
        for path in (scratch.installation.state_dir / "unit-logs").glob(f"{CHANGE}-01-*.log")
    }


def logs_since(scratch: Scratch, before: set[str]) -> str:
    """The run logs a tick wrote: those that were not there before it."""
    directory = scratch.installation.state_dir / "unit-logs"
    return "\n".join((directory / name).read_text() for name in sorted(log_names(scratch) - before))


def build_session_of(scratch: Scratch) -> str:
    """The unit's build session, as its thread in the checkpoint store records it."""

    async def read() -> str:
        async with open_checkpointer(unit_graphs_path(scratch.installation.state_dir)) as saver:
            state = (await thread_position(saver, UNIT_ID)).state
            assert state is not None, "the unit has no thread"
            return state.sessions[SessionRole.BUILD].session_id

    return asyncio.run(read())


COUNTED_ROUND = re.compile(r"(?<!address )review round \d+ \(")


def assert_chat_review_uncounted(log: str) -> None:
    """The review of a chat's commit comes first and is no counted round. A reviewer that asks
    for changes may well lead to counted rounds after the rework, and to the rounds running
    out; that is the loop working, so only a hold or a counted round with no counted round
    before it is a failure."""
    chat = log.find(CHAT_COMMIT_REVIEW)
    assert chat >= 0, log
    counted = [m.start() for m in COUNTED_ROUND.finditer(log)]
    assert not counted or counted[0] > chat, f"a counted round came before it\n{log}"
    spent = log.find("rounds spent")
    assert spent < 0 or (counted and counted[0] < spent), (
        f"the chat's commit alone held the unit for spent rounds\n{log}"
    )


def adopted_from(tree: Path, commit: str) -> str:
    return git(
        tree, "log", "-1", "--format=%(trailers:key=Adopted-From,valueonly,separator=)", commit
    ).strip()


def prompts_told(scratch: Scratch) -> str:
    return scratch.prompts.read_text() if scratch.prompts.exists() else ""


def changed(tree: Path) -> list[str]:
    return sorted(git(tree, "ls-files", "--modified", "--others", "--exclude-standard").split())


def head(path: Path) -> str:
    return git(path, "rev-parse", "HEAD").strip()


def converse(api: httpx.Client, url: str, body: dict[str, Any]) -> list[dict[str, Any]]:
    """A turn's whole reply. A permission the agent asks for is allowed once, as a person
    clicking through the page would."""
    from tests.chat_serving import events_of

    events: list[dict[str, Any]] = []
    with api.stream("POST", url, json=body) as response:
        assert response.status_code == 200, response.read()
        for event in events_of(response):
            events.append(event)
            if event.get("type") == "CUSTOM" and event.get("name") == "permission_request":
                options = event["value"]["options"]
                allow = next(o["id"] for o in options if str(o["kind"]).startswith("allow"))
                api.post(f"/api/permissions/{event['value']['id']}", json={"option": allow})
    return events


def said(events: list[dict[str, Any]]) -> str:
    """What the reply said, then any error it ended with, so a failure shows both."""
    text = "".join(
        str(e.get("delta", "")) for e in events if e.get("type") == "TEXT_MESSAGE_CONTENT"
    )
    errors = [str(e.get("message", e)) for e in events if e.get("type") == "RUN_ERROR"]
    return "\n".join([text, *(f"RUN_ERROR: {error}" for error in errors)])


@pytest.fixture(scope="module")
def in_review(scratch: Scratch) -> Scratch:
    """The unit built by the tick, waiting in review with a pull request."""
    built = run_tick(scratch)
    assert built.returncode == 0, built.output
    assert commits_on_unit_branch(scratch, BRANCH, built), built.output
    assert scratch.host.requests("POST", "/repos/example/app/pulls"), (
        f"{run_log(scratch)}\n{built.output}"
    )
    return scratch


def test_a_request_against_a_requirement_is_flagged_and_changes_nothing(
    in_review: Scratch, api: httpx.Client
) -> None:
    scratch = in_review
    before = head(scratch.tree)

    events = converse(
        api,
        f"{UNIT_URL}/chat",
        {
            "tab": "flag",
            "prompt": 'Change `marker()` so that it returns "unmarked" instead of "marked".',
        },
    )

    flags = [e for e in events if e.get("type") == "CUSTOM" and e.get("name") == "spec_conflict"]
    assert flags, f"no flag in the reply\n{said(events)}"
    assert "marker" in str(flags[0]["value"].get("requirement", "")).lower(), flags[0]
    assert changed(scratch.tree) == [], "a flagged request changed a file"
    assert head(scratch.tree) == before
    api.delete(f"{UNIT_URL}/lease", params={"tab": "flag"})


def test_a_chat_edit_is_fixed_for_the_hook_committed_and_reviewed_without_a_round(
    in_review: Scratch, api: httpx.Client
) -> None:
    scratch = in_review
    tree = scratch.tree
    hooks = Path(git(tree, "rev-parse", "--path-format=absolute", "--git-common-dir").strip())
    (hooks / "hooks").mkdir(exist_ok=True)
    hook = hooks / "hooks" / "pre-commit"
    hook.write_text(HOOK)
    hook.chmod(0o755)
    before = head(tree)

    edited = converse(
        api,
        f"{UNIT_URL}/chat",
        {
            "tab": "edit",
            "prompt": (
                "Add a second test to tests/test_marker.py asserting that `marker()` returns a "
                "str, and give `marker()` in src/app/marker.py a one-line docstring that ends "
                f"with the words {HOOK_MARKER} (as a literal word, not a comment). "
                "Edit the files only: do not commit."
            ),
        },
    )

    files = changed(tree)
    assert any(f.startswith("tests/") for f in files), f"{files}\n{said(edited)}"
    assert "src/app/marker.py" in files, f"{files}\n{said(edited)}"
    assert head(tree) == before, "a chat turn moved the branch head"
    listed = api.get(f"{UNIT_URL}/changes", params={"tab": "edit"}).json()["files"]
    assert set(listed) == set(files)
    held = Leases(lease_dir(scratch.installation.state_dir)).attachment(UNIT_ID)
    assert held is not None and held.changed == len(files)

    done = api.post(
        f"{UNIT_URL}/commit", json={"tab": "edit", "message": "Test the type of marker()"}
    )

    assert done.status_code == 200, done.text
    result = done.json()
    assert result["delivered"] is True
    assert head(tree) == result["commit"] != before
    assert HOOK_MARKER not in git(tree, "show", "--format=", result["commit"])
    runs = (hooks / "hook-runs").read_text().split()
    assert len(runs) >= 2, "the hook rejected nothing, so the agent fixed nothing"
    build_commit_session = adopted_from(tree, result["commit"])
    assert build_commit_session, "the commit names no session"
    assert build_commit_session == build_session_of(scratch), "not the build session's own commit"
    assert Leases(lease_dir(scratch.installation.state_dir)).attachment(UNIT_ID) is None

    logs_before = log_names(scratch)
    ticked = run_tick(scratch)
    assert ticked.returncode == 0, ticked.output
    log = logs_since(scratch, logs_before)
    assert CHAT_COMMIT_REVIEW in log, log
    assert_chat_review_uncounted(log)
    assert OUTSIDE_NOTE not in prompts_told(scratch), "the build session's own commit is outside"
    assert git(scratch.remote, "rev-parse", BRANCH).strip() == head(tree)


def test_a_free_session_changes_code_and_a_task_file_and_each_checkout_is_committed(
    in_review: Scratch, api: httpx.Client
) -> None:
    scratch = in_review
    tree = scratch.tree
    tasks = scratch.planning / "openspec" / "changes" / CHANGE / "tasks.md"
    before = (head(tree), head(scratch.planning))

    started = converse(
        api,
        "/api/sessions",
        {
            "tab": "free",
            "runtime": scratch.runtime,
            "unit": UNIT_ID,
            "prompt": (
                'Add a one-line module docstring `"""The marker module."""` at the top of '
                f"src/app/marker.py in {tree}, and in {tasks} "
                "change the group title `Add the marker` to `Add the marker function`. "
                "Edit the files only: do not commit."
            ),
        },
    )

    assert "The marker module." in (tree / "src/app/marker.py").read_text(), said(started)
    assert "Add the marker function" in tasks.read_text(), said(started)
    assert (head(tree), head(scratch.planning)) == before, "a free session committed"
    held = Leases(lease_dir(scratch.installation.state_dir)).attachment(UNIT_ID)
    assert held is not None and set(held.checkouts) == {"worktree", "planning"}

    spec = api.post(
        f"{UNIT_URL}/commit",
        json={"tab": "free", "message": "Reword the task", "checkouts": ["planning"]},
    )
    assert spec.status_code == 200, spec.text
    assert spec.json()["delivered"] is False, "a planning commit is delivered to no unit"
    assert head(scratch.planning) != before[1]
    assert head(tree) == before[0], "the planning commit touched the worktree"

    code = api.post(
        f"{UNIT_URL}/commit",
        json={"tab": "free", "message": "Add a version", "checkouts": ["worktree"]},
    )
    assert code.status_code == 200, code.text
    assert code.json()["delivered"] is True
    free_session = adopted_from(tree, code.json()["commit"])
    assert free_session, "the free session's commit names no session"
    assert free_session != build_session_of(scratch), "it was taken for the build session's"
    assert Leases(lease_dir(scratch.installation.state_dir)).attachment(UNIT_ID) is None

    logs_before = log_names(scratch)
    ticked = run_tick(scratch)
    assert ticked.returncode == 0, ticked.output
    log = logs_since(scratch, logs_before)
    assert CHAT_COMMIT_REVIEW in log, log
    assert_chat_review_uncounted(log)


def test_the_next_rework_lists_the_outside_commit_as_authoritative(in_review: Scratch) -> None:
    scratch = in_review
    outside = git(scratch.tree, "log", "-1", "--format=%H", "--grep=Add a version").strip()
    assert outside, "the free session's commit is not on the branch"
    scratch.host.add_review(7, "COMMENTED", "", inline=("src/app/marker.py", 1, COMMENT))

    told_before, logs_before = len(prompts_told(scratch)), log_names(scratch)

    reworked = run_tick(scratch)

    assert reworked.returncode == 0, reworked.output
    told = prompts_told(scratch)[told_before:]
    log = logs_since(scratch, logs_before)
    assert "address review round" in log or "rework from feedback" in log, log
    assert COMMENT in told, f"the rework was not handed the review comment\n{log}"
    assert OUTSIDE_NOTE in told, f"the rework was not told of the outside commit\n{log}"
    assert outside[:9] in told
    assert "Add a version" in told
    assert "The marker module." in git(scratch.remote, "show", f"{BRANCH}:src/app/marker.py"), (
        "the rework reverted the outside commit"
    )


def test_a_stale_attachment_is_released_from_the_command_line(in_review: Scratch) -> None:
    scratch = in_review
    tree = scratch.tree
    (tree / "stray.txt").write_text("left by a chat\n")
    leave_lease(lease_dir(scratch.installation.state_dir), UNIT_ID, files=1)
    held = Leases(lease_dir(scratch.installation.state_dir)).attachment(UNIT_ID)
    assert held is not None and held.stale

    refused = abk(scratch, "attach", "release", UNIT_ID)
    assert refused.returncode != 0
    assert "--commit" in refused.output and "--discard" in refused.output, refused.output
    assert (tree / "stray.txt").exists(), "a refused release changed the tree"

    released = abk(scratch, "attach", "release", UNIT_ID, "--discard")

    assert released.returncode == 0, released.output
    assert not (tree / "stray.txt").exists()
    assert changed(tree) == []
    assert Leases(lease_dir(scratch.installation.state_dir)).attachment(UNIT_ID) is None
