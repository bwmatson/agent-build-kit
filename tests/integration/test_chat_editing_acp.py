"""Editing from chat over a real scratch installation: a chat edit to a reviewed commit.

The agent is a real one on this host (`ABK_ACCEPTANCE_ACP_COMMAND`), reached through a recorder
that copies what is written to its stdin into a file, so what the pipeline told it is read at the
protocol boundary. `abk tick` and `abk attach release` are the real CLI run as processes, and the
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

Needs an agent speaking the protocol, node for the OpenSpec CLI and uv. Bills on demand and takes
minutes, so it is marked tier 2 and excluded from the default suite.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import textwrap
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from agent_build_kit import config
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

pytestmark = [
    pytest.mark.local_stack,
    pytest.mark.skipif(shutil.which("npx") is None, reason="npx is not on PATH"),
    pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not on PATH"),
]

CHANGE = "add-marker"
BRANCH = f"spec/{CHANGE}/1"
UNIT_ID = f"{CHANGE}/1"
UNIT_URL = f"/api/units/{CHANGE}/1"
AGENT_COMMAND = "ABK_ACCEPTANCE_ACP_COMMAND"
HOOK_MARKER = "FIXME-CHAT"
OUTSIDE_NOTE = "Commits made outside this session"
CHAT_COMMIT_REVIEW = "review of a chat's commit"
COMMENT = "Please also say in the docstring of `marker()` that it is a marker."

TASKS = """# Tasks

## 1. [app] [tier1] Add the marker

- [ ] 1.1 Test: `marker()` in `src/app/marker.py` returns the string `"marked"`.
- [ ] 1.2 Add `marker()` to `src/app/marker.py`.

Acceptance: none — a single function whose own test is its proof
"""

# Stands between the pipeline and the agent: the agent's stdin is copied to a file as it is read.
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


class Ticked(Frozen):
    returncode: int
    output: str


class Scratch(Frozen):
    model_config = {"arbitrary_types_allowed": True}

    planning: Path
    app: Path
    remote: Path
    installation: Installation
    prompts: Path
    host: FakeGitHub
    env: dict[str, str]

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


@pytest.fixture(scope="module")
def scratch(tmp_path_factory: pytest.TempPathFactory, github_host: FakeGitHub) -> Scratch:
    tmp_path = tmp_path_factory.mktemp("chat-editing")
    command = os.environ.get(AGENT_COMMAND, "")
    if not command:
        pytest.fail(f"{AGENT_COMMAND} names no agent: this run needs a real one on the host")
    prompts = tmp_path / "prompts.log"
    recorder = tmp_path / "recorder.py"
    recorder.write_text(RECORDER)

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
    wrapped = [sys.executable, str(recorder), str(prompts), *shlex.split(command)]
    (planning / "abk.yaml").write_text(
        f"repos:\n  app:\n    path: {app}\n    slug: example/app\n"
        "    profile: python-uv\n    languages: [python]\n"
        f"planning:\n  worktree_root: {tmp_path / 'worktrees'}\n"
        f"runtimes:\n  acp:\n    command: {wrapped}\n"
    )
    (planning / ".gitignore").write_text("runs/\n")
    git(planning, "add", "-A")
    git(planning, "commit", "-q", "-m", "plan")

    env = {
        **process_env(github_host, tmp_path / "bin", tmp_path / "gh-calls.txt"),
        "ABK_CONFIG": str(planning / "abk.yaml"),
        "ABK_WORKTREE_ROOT": str(tmp_path / "worktrees"),
        "ABK_RUNTIME": "acp",
    }
    return Scratch(
        planning=planning,
        app=app,
        remote=remote,
        installation=Installation(config.load(planning / "abk.yaml"), planning),
        prompts=prompts,
        host=github_host,
        env=env,
    )


@pytest.fixture(scope="module")
def api(scratch: Scratch) -> Iterator[httpx.Client]:
    with (
        start_server(scratch.installation) as server,
        httpx.Client(base_url=server.url, timeout=1800) as client,
    ):
        yield client


def abk(scratch: Scratch, *args: str) -> Ticked:
    run = subprocess.run(
        [str(Path(sys.executable).parent / "abk"), *args],
        cwd=scratch.planning,
        env=scratch.env,
        capture_output=True,
        text=True,
        timeout=3600,
    )
    return Ticked(returncode=run.returncode, output=run.stdout + run.stderr)


def run_log(scratch: Scratch) -> str:
    logs = sorted((scratch.installation.state_dir / "unit-logs").glob(f"{CHANGE}-01-*.log"))
    return "\n".join(path.read_text() for path in logs)


def prompts_told(scratch: Scratch) -> str:
    return scratch.prompts.read_text() if scratch.prompts.exists() else ""


def status_of(scratch: Scratch) -> Any:
    return UnitStore(scratch.installation.state_dir / "units.json").get(UNIT_ID)


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
                allow = next(o["id"] for o in options if o["kind"] == "allow_once")
                api.post(f"/api/permissions/{event['value']['id']}", json={"option": allow})
    return events


def said(events: list[dict[str, Any]]) -> str:
    return "".join(
        str(e.get("delta", "")) for e in events if e.get("type") == "TEXT_MESSAGE_CONTENT"
    )


@pytest.fixture(scope="module")
def in_review(scratch: Scratch) -> Scratch:
    """The unit built by the tick, waiting in review with a pull request."""
    built = abk(scratch, "tick")
    assert built.returncode == 0, built.output
    assert scratch.host.requests("POST", "/repos/example/app/pulls"), run_log(scratch)
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
    rounds_before = run_log(scratch).count("review round")

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
    assert "Adopted-From" in git(tree, "log", "-1", "--format=%B", result["commit"])
    assert Leases(lease_dir(scratch.installation.state_dir)).attachment(UNIT_ID) is None

    ticked = abk(scratch, "tick")
    assert ticked.returncode == 0, ticked.output
    log = run_log(scratch)
    assert CHAT_COMMIT_REVIEW in log, log
    assert log.count("review round") == rounds_before, "the chat's commit took a review round"
    assert status_of(scratch).cause is None or status_of(scratch).cause.value != "review_spent"
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
            "runtime": "acp",
            "unit": UNIT_ID,
            "prompt": (
                f"Add the line `VERSION = 1` to src/app/marker.py in {tree}, and in {tasks} "
                "change the group title `Add the marker` to `Add the marker function`. "
                "Edit the files only: do not commit."
            ),
        },
    )

    assert "VERSION = 1" in (tree / "src/app/marker.py").read_text(), said(started)
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
    assert "Adopted-From" in git(tree, "log", "-1", "--format=%B", code.json()["commit"])
    assert Leases(lease_dir(scratch.installation.state_dir)).attachment(UNIT_ID) is None

    ticked = abk(scratch, "tick")
    assert ticked.returncode == 0, ticked.output
    assert CHAT_COMMIT_REVIEW in run_log(scratch)


def test_the_next_rework_lists_the_outside_commit_as_authoritative(in_review: Scratch) -> None:
    scratch = in_review
    outside = git(scratch.tree, "log", "-1", "--format=%H", "--grep=Add a version").strip()
    assert outside, "the free session's commit is not on the branch"
    scratch.host.add_review(7, "COMMENTED", "", inline=("src/app/marker.py", 1, COMMENT))

    reworked = abk(scratch, "tick")

    assert reworked.returncode == 0, reworked.output
    told = prompts_told(scratch)
    assert OUTSIDE_NOTE in told, (
        f"the rework was not told of the outside commit\n{run_log(scratch)}"
    )
    assert outside[:9] in told
    assert "Add a version" in told
    assert "VERSION = 1" in git(scratch.remote, "show", f"{BRANCH}:src/app/marker.py"), (
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
