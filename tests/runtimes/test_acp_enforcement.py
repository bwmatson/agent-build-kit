"""How the `acp` adapter holds an agent to abk's rules, at both points the
protocol offers.

- **The client does the work.** The adapter advertises the file and terminal
  capabilities, so an agent that defers to them has abk run every command and
  perform every write itself: `command_policy`'s rules decide a command before
  it runs, and a write lands only inside the unit's worktree and never in the
  planning repo's specs.
- **The agent does the work, and asks.** An agent that runs its own tools asks
  permission for the calls it chooses to, offering options of its own; the
  adapter answers with the same rules, picking a refusing option by its kind —
  and, when no option refuses, cancels the turn rather than permit the call.

The agent is a real subprocess speaking the protocol (`acp_agent.py`), whose
`did/*` record says what it asked for and what it was answered. Each refusal
is tested beside an allowed call in the same run, so a refusal is the rules'
and not a capability that was never there.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.pipeline.command_policy import check_command, check_no_commit, check_no_push
from agent_build_kit.runtimes import AgentRequest, ToolPolicy
from agent_build_kit.runtimes.acp import AcpRuntime, _Session
from tests.factories import git, init_repo
from tests.runtimes.acp_agent import requests, use_agent

BRANCH = "spec/add-marker/1"
ALLOWED = {"terminal": "git", "args": ["rev-parse", "--abbrev-ref", "HEAD"]}


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    """A unit's worktree: on its branch, one commit in, with a directory a
    recursive delete would take."""
    path = init_repo(tmp_path / "worktree")
    (path / "src").mkdir()
    (path / "src" / "app.py").write_text("MARKER = None\n")
    (path / "victim").mkdir()
    (path / "victim" / "keep.txt").write_text("keep\n")
    git(path, "checkout", "-q", "-b", BRANCH)
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "start")
    return path


@pytest.fixture
def specs(tmp_path: Path) -> Path:
    path = tmp_path / "planning" / "openspec" / "specs"
    (path / "feature").mkdir(parents=True)
    (path / "feature" / "spec.md").write_text("# Feature\n")
    return path


@pytest.fixture
def other_checkout(tmp_path: Path) -> Path:
    """Someone else's checkout beside the worktree: not the unit's to change."""
    return init_repo(tmp_path / "other")


def _run(record: Path, worktree: Path, specs: Path, **agent: Any):
    use_agent(record, **agent)
    return AcpRuntime().run(
        AgentRequest(
            prompt="Implement group 1 of add-marker.",
            role="implement",
            cwd=worktree,
            add_dirs=(specs,),
            policy=ToolPolicy(specs_dir=specs),
        )
    )


def _did(record: Path, what: str) -> list[dict[str, Any]]:
    return requests(record, f"did/{what}")


# --- the client does the work --------------------------------------------------------


def test_the_file_and_terminal_capabilities_are_advertised(
    tmp_path: Path, worktree: Path, specs: Path
) -> None:
    """An agent must not call a capability the client did not advertise, so
    abk can only run the work itself for an agent that was told it may ask."""
    record = tmp_path / "agent.jsonl"

    _run(record, worktree, specs, act=[])

    [initialized] = requests(record, "initialize")
    capabilities = initialized["clientCapabilities"]
    assert capabilities["fs"]["readTextFile"] is True
    assert capabilities["fs"]["writeTextFile"] is True
    assert capabilities["terminal"] is True


def test_an_allowed_command_runs_in_the_worktree_and_its_output_comes_back(
    tmp_path: Path, worktree: Path, specs: Path
) -> None:
    record = tmp_path / "agent.jsonl"

    result = _run(record, worktree, specs, act=[ALLOWED])

    assert result.ok is True
    [ran] = _did(record, "terminal")
    assert "error" not in ran, ran
    assert ran["exitCode"] == 0
    assert ran["output"].strip() == BRANCH


FORBIDDEN = [
    pytest.param("rm", ["-rf", "victim"], id="recursive-delete"),
    pytest.param("git status && rm -rf victim", [], id="behind-another-command-as-one-string"),
    pytest.param("git", ["reset", "--hard", "HEAD"], id="hard-reset"),
]


@pytest.mark.parametrize(("command", "args"), FORBIDDEN)
def test_a_forbidden_command_is_never_run_and_the_agent_is_told_why(
    tmp_path: Path, worktree: Path, specs: Path, command: str, args: list[str]
) -> None:
    """Refused by `command_policy` before anything runs — a recursive delete
    leaves its directory, a hard reset leaves the change it would discard —
    and the agent hears the rule's own reason, so it can carry on another way."""
    record = tmp_path / "agent.jsonl"
    (worktree / "src" / "app.py").write_text('MARKER = "uncommitted"\n')
    line = " ".join([command, *args])
    reason = check_command(line, branch=BRANCH).reason
    assert reason, f"{line!r} is meant to be one the rules forbid"

    result = _run(record, worktree, specs, act=[{"terminal": command, "args": args}, ALLOWED])

    assert (worktree / "victim" / "keep.txt").exists()
    assert (worktree / "src" / "app.py").read_text() == 'MARKER = "uncommitted"\n'
    refused, allowed = _did(record, "terminal")
    assert "error" in refused or refused.get("exitCode") != 0, refused
    assert reason in json.dumps(refused), refused
    # The run goes on: one refusal is not the end of the unit.
    assert allowed["output"].strip() == BRANCH
    assert result.ok is True


PUSHES = [
    pytest.param("git", ["push", "origin", BRANCH], id="its-own-branch"),
    pytest.param("git push -u origin HEAD", [], id="as-one-string"),
    pytest.param("git status && git push origin " + BRANCH, [], id="behind-another-command"),
]


@pytest.mark.parametrize(("command", "args"), PUSHES)
def test_a_push_is_never_run_even_to_the_units_own_branch(
    tmp_path: Path, worktree: Path, specs: Path, command: str, args: list[str]
) -> None:
    """The pipeline's push is the only one the branch may receive: its lease
    names the commit it last published, so any other push fails it later."""
    record = tmp_path / "agent.jsonl"
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", str(remote))
    git(worktree, "remote", "add", "origin", str(remote))

    _run(record, worktree, specs, act=[{"terminal": command, "args": args}, ALLOWED])

    refused, _ = _did(record, "terminal")
    assert "error" in refused or refused.get("exitCode") != 0, refused
    assert check_no_push(" ".join([command, *args])).reason in json.dumps(
        refused, ensure_ascii=False
    ), refused
    assert git(remote, "branch", "--list").strip() == ""


def test_a_push_the_agent_asks_about_is_refused(
    tmp_path: Path, worktree: Path, specs: Path
) -> None:
    record = tmp_path / "agent.jsonl"

    _run(record, worktree, specs, act=[{"ask": "execute", "command": f"git push origin {BRANCH}"}])

    [answer] = _answered(record)
    assert answer["optionKind"] in ("reject_once", "reject_always"), answer
    assert _did(record, "run") == []


def test_a_write_inside_the_worktree_is_performed(
    tmp_path: Path, worktree: Path, specs: Path
) -> None:
    record = tmp_path / "agent.jsonl"
    target = worktree / "src" / "marker.py"

    result = _run(
        record, worktree, specs, act=[{"write": str(target), "content": 'MARKER = "added"\n'}]
    )

    assert result.ok is True
    [wrote] = _did(record, "write")
    assert "error" not in wrote, wrote
    assert target.read_text() == 'MARKER = "added"\n'


def _escapes(worktree: Path, specs: Path, other: Path) -> dict[str, Path]:
    link = worktree / "src" / "elsewhere"
    link.symlink_to(other, target_is_directory=True)
    return {
        "another-checkout": other / "notes.txt",
        "climbing-out-of-the-worktree": worktree / ".." / "other" / "climbed.txt",
        "through-a-link-in-the-worktree": link / "linked.txt",
        "the-specs-directory": specs / "feature" / "spec.md",
        "a-new-file-in-the-specs-directory": specs / "feature" / "tasks.md",
    }


@pytest.mark.parametrize(
    "where",
    [
        "another-checkout",
        "climbing-out-of-the-worktree",
        "through-a-link-in-the-worktree",
        "the-specs-directory",
        "a-new-file-in-the-specs-directory",
    ],
)
def test_a_write_outside_the_worktree_or_into_the_specs_is_not_performed(
    tmp_path: Path, worktree: Path, specs: Path, other_checkout: Path, where: str
) -> None:
    """The specs are readable but not the build's to change; anything outside
    the worktree is no commit's to pick up. Resolved, so neither `..` nor a
    link inside the worktree is a way out."""
    record = tmp_path / "agent.jsonl"
    target = _escapes(worktree, specs, other_checkout)[where]
    before = target.read_text() if target.exists() else None
    inside = worktree / "src" / "marker.py"

    result = _run(
        record,
        worktree,
        specs,
        act=[
            {"write": str(target), "content": "overwritten\n"},
            {"write": str(inside), "content": 'MARKER = "added"\n'},
        ],
    )

    assert (target.read_text() if target.exists() else None) == before
    refused, performed = _did(record, "write")
    assert "error" in refused, refused
    assert "error" not in performed, performed
    assert inside.read_text() == 'MARKER = "added"\n'
    assert result.ok is True


def test_the_worktree_and_the_specs_are_readable(
    tmp_path: Path, worktree: Path, specs: Path
) -> None:
    """An agent that writes through the client reads through it too: the
    worktree it works in, and the specs it builds from."""
    record = tmp_path / "agent.jsonl"

    _run(
        record,
        worktree,
        specs,
        act=[
            {"read": str(worktree / "src" / "app.py")},
            {"read": str(specs / "feature" / "spec.md")},
        ],
    )

    source, spec = _did(record, "read")
    assert source.get("content") == "MARKER = None\n", source
    assert spec.get("content") == "# Feature\n", spec


# --- the agent does the work, and asks ------------------------------------------------


def _answered(record: Path) -> list[dict[str, Any]]:
    return _did(record, "ask")


def test_a_forbidden_command_the_agent_asks_about_is_refused(
    tmp_path: Path, worktree: Path, specs: Path
) -> None:
    """Answered by kind, not by id: the ids are the agent's own words."""
    record = tmp_path / "agent.jsonl"

    result = _run(record, worktree, specs, act=[{"ask": "execute", "command": "rm -rf victim"}])

    [answer] = _answered(record)
    assert answer["outcome"] == "selected", answer
    assert answer["optionKind"] in ("reject_once", "reject_always"), answer
    assert _did(record, "run") == []
    assert result.ok is True


def test_an_allowed_command_the_agent_asks_about_is_allowed_once(
    tmp_path: Path, worktree: Path, specs: Path
) -> None:
    """Once, never always: an agent told "always" stops asking about what it
    thinks is the same kind of call, and the next one may not be."""
    record = tmp_path / "agent.jsonl"

    _run(record, worktree, specs, act=[{"ask": "execute", "command": "git status --short"}])

    [answer] = _answered(record)
    assert answer["optionKind"] == "allow_once", answer
    assert [ran["command"] for ran in _did(record, "run")] == ["git status --short"]


@pytest.mark.parametrize("locations", [True, False], ids=["as-locations", "as-raw-path"])
def test_an_edit_naming_a_relative_path_is_weighed_against_the_session_cwd(
    tmp_path: Path, worktree: Path, specs: Path, locations: bool
) -> None:
    """Relative to the worktree the session opened in — not to abk's own
    directory — and through a link to it, as a worktree under a symlinked
    /tmp is reached; an agent may also send no `locations` at all."""
    record = tmp_path / "agent.jsonl"
    link = tmp_path / "linked"
    link.symlink_to(worktree)

    _run(
        record,
        link,
        specs,
        act=[
            {"ask": "edit", "paths": ["src/app.py"], "locations": locations},
            {"ask": "edit", "paths": ["../outside.txt"], "locations": locations},
        ],
    )

    allowed, refused = _answered(record)
    assert allowed["optionKind"] == "allow_once", allowed
    assert refused["optionKind"] in ("reject_once", "reject_always"), refused


def test_an_edit_inside_the_worktree_is_allowed(
    tmp_path: Path, worktree: Path, specs: Path
) -> None:
    record = tmp_path / "agent.jsonl"

    _run(
        record,
        worktree,
        specs,
        act=[{"ask": "edit", "paths": [str(worktree / "src" / "app.py")]}],
    )

    [answer] = _answered(record)
    assert answer["optionKind"] == "allow_once", answer


@pytest.mark.parametrize(
    "where",
    [
        "another-checkout",
        "climbing-out-of-the-worktree",
        "through-a-link-in-the-worktree",
        "the-specs-directory",
        "a-new-file-in-the-specs-directory",
    ],
)
def test_an_edit_naming_a_path_outside_the_worktree_is_refused(
    tmp_path: Path, worktree: Path, specs: Path, other_checkout: Path, where: str
) -> None:
    """Answered from every path the request names: one inside does not carry
    one outside with it."""
    record = tmp_path / "agent.jsonl"
    outside = _escapes(worktree, specs, other_checkout)[where]

    _run(
        record,
        worktree,
        specs,
        act=[{"ask": "edit", "paths": [str(worktree / "src" / "app.py"), str(outside)]}],
    )

    [answer] = _answered(record)
    assert answer["outcome"] == "selected", answer
    assert answer["optionKind"] in ("reject_once", "reject_always"), answer
    assert _did(record, "run") == []


def test_an_edit_naming_no_path_is_refused(tmp_path: Path, worktree: Path, specs: Path) -> None:
    """With nothing to resolve against the worktree there is nothing to vouch
    for, and guessing "allow" is how a guard gets bypassed."""
    record = tmp_path / "agent.jsonl"

    _run(record, worktree, specs, act=[{"ask": "edit", "paths": []}])

    [answer] = _answered(record)
    assert answer["optionKind"] in ("reject_once", "reject_always"), answer
    assert _did(record, "run") == []


def test_a_forbidden_command_with_no_way_to_refuse_cancels_the_turn(
    tmp_path: Path, worktree: Path, specs: Path
) -> None:
    """Only permitting options on offer: picking one would invert the
    guarantee, so the turn is cancelled. The cancel is abk's own doing and
    would recur on a retry, so the run is a failed result saying why, not an
    interruption to reclaim."""
    record = tmp_path / "agent.jsonl"

    result = _run(
        record,
        worktree,
        specs,
        act=[
            {
                "ask": "execute",
                "command": "rm -rf victim",
                "options": ["allow_once", "allow_always"],
            }
        ],
    )

    [answer] = _answered(record)
    assert answer["outcome"] == "cancelled", answer
    assert requests(record, "session/cancel"), "the turn was not cancelled"
    assert _did(record, "run") == []
    assert result.ok is False
    assert "refus" in result.error.lower(), result.error


# --- what the options allow ----------------------------------------------------------


def test_an_allowed_command_is_never_answered_with_an_always_option(
    tmp_path: Path, worktree: Path, specs: Path
) -> None:
    """With no `allow_once` on offer the call is answered cancelled and
    nothing runs; the turn is not cancelled on its account."""
    record = tmp_path / "agent.jsonl"

    result = _run(
        record,
        worktree,
        specs,
        act=[
            {
                "ask": "execute",
                "command": "git status",
                "options": ["allow_always"],
                "carry_on": True,
            }
        ],
    )

    [answer] = _answered(record)
    assert answer["outcome"] == "cancelled", answer
    assert _did(record, "run") == []
    assert not requests(record, "session/cancel")
    assert result.ok is True


# --- a run with nothing to enforce ---------------------------------------------------


def test_an_unpoliced_run_is_answered_method_not_found_for_file_and_terminal_work(
    tmp_path: Path, worktree: Path
) -> None:
    record = tmp_path / "agent.jsonl"
    use_agent(
        record,
        act=[
            {"terminal": "touch", "args": ["ran-unpoliced"]},
            {"write": str(worktree / "written-unpoliced"), "content": "x\n"},
            {"read": str(worktree / "src" / "app.py")},
        ],
    )

    result = AcpRuntime().run(AgentRequest(prompt="Read only.", role="review", cwd=worktree))

    assert result.ok is True
    assert not (worktree / "ran-unpoliced").exists()
    assert not (worktree / "written-unpoliced").exists()
    [terminal] = _did(record, "terminal")
    [wrote] = _did(record, "write")
    [read] = _did(record, "read")
    for entry in (terminal, wrote, read):
        assert entry["error"]["code"] == -32601, entry
        assert "content" not in entry


def test_a_run_relying_on_headless_denial_has_every_permission_request_refused(
    tmp_path: Path, worktree: Path
) -> None:
    """The planner's graph call: no tool list and `allowed_tools_only`, so
    nothing it asks about is granted, allowed by the rules or not."""
    record = tmp_path / "agent.jsonl"
    use_agent(record, act=[{"ask": "execute", "command": "git status --short"}])

    result = AcpRuntime().run(
        AgentRequest(
            prompt="Plan.", role="generic", cwd=worktree, permission_mode="allowed_tools_only"
        )
    )

    [answer] = _answered(record)
    assert answer["optionKind"] in ("reject_once", "reject_always"), answer
    assert _did(record, "run") == []
    assert result.ok is True


# --- answering by what the request names ---------------------------------------------


def test_a_read_of_the_specs_or_an_extra_directory_is_allowed_but_an_edit_there_is_not(
    tmp_path: Path, worktree: Path, specs: Path
) -> None:
    record = tmp_path / "agent.jsonl"
    extra = tmp_path / "reference"
    extra.mkdir()
    (extra / "notes.md").write_text("notes\n")
    spec = str(specs / "feature" / "spec.md")
    use_agent(
        record,
        act=[
            {"ask": "read", "paths": [spec]},
            {"ask": "read", "paths": [str(extra / "notes.md")]},
            {"ask": "read", "paths": [str(tmp_path / "elsewhere.txt")]},
            {"ask": "edit", "paths": [spec]},
        ],
    )

    AcpRuntime().run(
        AgentRequest(
            prompt="Build.",
            role="implement",
            cwd=worktree,
            add_dirs=(specs, extra),
            policy=ToolPolicy(specs_dir=specs),
        )
    )

    kinds = [answer["optionKind"] for answer in _answered(record)]
    assert kinds[:2] == ["allow_once", "allow_once"], kinds
    assert kinds[2] in ("reject_once", "reject_always"), kinds
    assert kinds[3] in ("reject_once", "reject_always"), kinds


def test_a_command_in_the_raw_input_is_weighed_whatever_the_kind(
    tmp_path: Path, worktree: Path, specs: Path
) -> None:
    record = tmp_path / "agent.jsonl"
    inside = str(worktree / "src" / "app.py")

    _run(
        record,
        worktree,
        specs,
        act=[
            {"ask": "other", "command": "gh pr merge 1", "paths": [inside]},
            {"ask": "other", "command": "git status", "paths": [inside]},
        ],
    )

    refused, allowed = _answered(record)
    assert refused["optionKind"] in ("reject_once", "reject_always"), refused
    assert allowed["optionKind"] == "allow_once", allowed
    assert [ran["command"] for ran in _did(record, "run")] == ["git status"]


@pytest.mark.parametrize(
    ("command", "paths", "permitted"),
    [
        pytest.param("rm -rf victim", [], False, id="forbidden-command"),
        pytest.param("git status --short", [], True, id="allowed-command"),
        pytest.param(None, ["src/app.py"], True, id="edit-in-the-worktree"),
        pytest.param(None, ["../outside.txt"], False, id="edit-outside-the-worktree"),
    ],
)
def test_a_permission_request_naming_only_its_id_is_answered_from_the_tool_calls_start(
    tmp_path: Path,
    worktree: Path,
    specs: Path,
    command: str | None,
    paths: list[str],
    permitted: bool,
) -> None:
    """The request's `toolCall` is an update: everything but the id may be
    absent, the start having said it."""
    record = tmp_path / "agent.jsonl"
    kind = "execute" if command else "edit"
    resolved = [str(worktree / path) for path in paths]

    _run(
        record,
        worktree,
        specs,
        act=[{"ask": kind, "command": command, "paths": resolved, "sparse": True}],
    )

    [answer] = _answered(record)
    if permitted:
        assert answer["optionKind"] == "allow_once", answer
    else:
        assert answer["optionKind"] in ("reject_once", "reject_always"), answer


# --- the terminal ---------------------------------------------------------------------


def test_a_whole_line_command_with_no_arguments_runs(
    tmp_path: Path, worktree: Path, specs: Path
) -> None:
    record = tmp_path / "agent.jsonl"

    _run(record, worktree, specs, act=[{"terminal": "git status --short", "args": []}])

    [ran] = _did(record, "terminal")
    assert "error" not in ran, ran
    assert ran["exitCode"] == 0


def test_a_command_reading_stdin_gets_none(tmp_path: Path, worktree: Path, specs: Path) -> None:
    """Not abk's own input, which is the agent's protocol stream's."""
    record = tmp_path / "agent.jsonl"
    # Pytest's own fd 0 is already the null device, so give abk's stdin
    # something to leak for the length of the run.
    leak = tmp_path / "leak.txt"
    leak.write_text("leak\n")
    saved = os.dup(0)
    with leak.open() as source:
        os.dup2(source.fileno(), 0)
    try:
        _run(record, worktree, specs, act=[{"terminal": "cat", "args": ["-"]}])
    finally:
        os.dup2(saved, 0)
        os.close(saved)

    [ran] = _did(record, "terminal")
    assert ran["exitCode"] == 0 and ran["output"] == "", ran


def test_a_released_terminals_id_is_not_handed_out_again(worktree: Path) -> None:
    """Two live terminals, the first released, then a third: three distinct
    ids, and nothing is left running once the run's terminals end."""

    async def scenario() -> tuple[list[str], list[Any]]:
        session = _Session(None, worktree=worktree, policy=ToolPolicy())
        first = await session.create_terminal("s", "sleep", ["30"])
        second = await session.create_terminal("s", "sleep", ["31"])
        survivor = session._terminals[second.terminal_id].process
        await session.release_terminal("s", first.terminal_id)
        third = await session.create_terminal("s", "sleep", ["32"])
        ids = [first.terminal_id, second.terminal_id, third.terminal_id]
        assert session._terminals[second.terminal_id].process is survivor
        processes = [t.process for t in session._terminals.values()]
        assert survivor.returncode is None
        await session.end_terminals()
        return ids, processes

    ids, processes = asyncio.run(scenario())

    assert len(set(ids)) == 3, ids
    assert all(p.returncode is not None for p in processes)


def test_a_hung_command_is_killed_when_the_agent_gives_up_on_it(
    tmp_path: Path, worktree: Path, specs: Path
) -> None:
    """`terminal/create` returns once the command has started, so the agent's
    own timeout can fire and kill it: the run finishes promptly and records
    the signal."""
    record = tmp_path / "agent.jsonl"
    started = time.monotonic()

    result = _run(
        record,
        worktree,
        specs,
        act=[{"terminal": "sleep", "args": ["60"], "kill_after": 0.3}],
    )

    assert time.monotonic() - started < 20
    [ran] = _did(record, "terminal")
    assert ran["signal"] == "SIGKILL", ran
    assert result.ok is True


def test_output_is_cut_to_the_byte_limit_from_the_front(
    tmp_path: Path, worktree: Path, specs: Path
) -> None:
    record = tmp_path / "agent.jsonl"

    _run(
        record,
        worktree,
        specs,
        act=[{"terminal": "printf", "args": ["abcdefghij"], "limit": 4}],
    )

    [ran] = _did(record, "terminal")
    assert ran["output"] == "ghij" and ran["truncated"] is True, ran


def test_the_branch_is_read_where_the_command_runs_on_every_call(
    tmp_path: Path, worktree: Path, specs: Path
) -> None:
    """A lease push is fine on the unit's branch; after a checkout of another
    through the terminal it is refused, and the rule's reason says why."""
    record = tmp_path / "agent.jsonl"
    push = ["push", "--force-with-lease=x:abc", "origin", "x"]
    reason = check_command(" ".join(["git", *push]), branch="other").reason
    assert reason

    _run(
        record,
        worktree,
        specs,
        act=[
            {"terminal": "git", "args": push},
            {"terminal": "git", "args": ["checkout", "-q", "-b", "other"]},
            {"terminal": "git", "args": push},
        ],
    )

    before, _checkout, after = _did(record, "terminal")
    assert "error" not in before or before["error"]["data"]["reason"] != reason, before
    assert after["error"]["data"]["reason"] == reason, after


def test_a_relative_path_is_read_and_written_in_the_worktree_not_abks_directory(
    tmp_path: Path, worktree: Path, specs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    elsewhere = tmp_path / "elsewhere"
    (elsewhere / "src").mkdir(parents=True)
    (elsewhere / "src" / "app.py").write_text("WRONG = True\n")
    monkeypatch.chdir(elsewhere)
    record = tmp_path / "agent.jsonl"

    _run(
        record,
        worktree,
        specs,
        act=[
            {"read": "src/app.py"},
            {"write": "src/new.py", "content": "NEW = 1\n"},
        ],
    )

    [read] = _did(record, "read")
    assert read["content"] == "MARKER = None\n", read
    assert (worktree / "src" / "new.py").read_text() == "NEW = 1\n"
    assert not (elsewhere / "src" / "new.py").exists()


# --- paging a file ---------------------------------------------------------------------


def test_a_read_honours_line_and_limit(tmp_path: Path, worktree: Path, specs: Path) -> None:
    record = tmp_path / "agent.jsonl"
    paged = worktree / "src" / "paged.txt"
    paged.write_text("one\ntwo\nthree\n")

    _run(record, worktree, specs, act=[{"read": str(paged), "line": 2, "limit": 1}])

    [read] = _did(record, "read")
    assert read["content"] == "two\n", read


# --- an edit approval titled with its path -------------------------------------------


def test_an_edit_approval_titled_with_its_path_is_weighed_on_that_path(
    tmp_path: Path, worktree: Path, specs: Path
) -> None:
    """An agent that asks for an edit with `Approve edit: <absolute path>` and
    neither a kind nor locations: the path is read from the title, and the
    worktree-and-not-specs check applies to it."""
    record = tmp_path / "agent.jsonl"
    inside = str(worktree / "src" / "marker.py")
    spec = str(specs / "feature" / "spec.md")

    _run(
        record,
        worktree,
        specs,
        act=[
            {"ask": "other", "title": f"Approve edit: {inside}", "locations": False},
            {"ask": "other", "title": f"Approve edit: {spec}", "locations": False},
        ],
    )

    inside_answer, spec_answer = _answered(record)
    assert inside_answer["optionKind"] == "allow_once", inside_answer
    assert spec_answer["optionKind"] in ("reject_once", "reject_always"), spec_answer


# --- a chat turn: the unit's builder may edit and cannot commit; a free session is bare -------


def _run_with(record: Path, worktree: Path, specs: Path, policy: ToolPolicy, **agent: Any):
    use_agent(record, **agent)
    return AcpRuntime().run(
        AgentRequest(
            prompt="Change it.", role="implement", cwd=worktree, add_dirs=(specs,), policy=policy
        )
    )


COMMITS = [
    pytest.param("git", ["commit", "-am", "wip"], id="plain"),
    pytest.param("git add -A && git commit -m wip", [], id="behind-another-command"),
]


@pytest.mark.parametrize(("command", "args"), COMMITS)
def test_a_turn_that_may_not_commit_edits_the_worktree_and_commits_nothing(
    tmp_path: Path, worktree: Path, specs: Path, command: str, args: list[str]
) -> None:
    record = tmp_path / "agent.jsonl"
    target = worktree / "src" / "marker.py"
    before = git(worktree, "rev-parse", "HEAD")

    _run_with(
        record,
        worktree,
        specs,
        ToolPolicy(specs_dir=specs, no_commit=True),
        act=[
            {"write": str(target), "content": 'MARKER = "edited"\n'},
            {"terminal": command, "args": args},
        ],
    )

    assert target.read_text() == 'MARKER = "edited"\n'
    [ran] = _did(record, "terminal")
    assert "error" in ran or ran.get("exitCode") != 0, ran
    assert check_no_commit(" ".join([command, *args])).reason in json.dumps(
        ran, ensure_ascii=False
    ), ran
    assert git(worktree, "rev-parse", "HEAD") == before, "the branch head did not move"


def test_a_free_sessions_turn_may_write_anywhere_and_still_cannot_commit_or_push(
    tmp_path: Path, worktree: Path, specs: Path, other_checkout: Path
) -> None:
    record = tmp_path / "agent.jsonl"
    elsewhere = other_checkout / "notes.txt"
    in_specs = specs / "feature" / "tasks.md"
    before = git(worktree, "rev-parse", "HEAD")

    _run_with(
        record,
        worktree,
        specs,
        ToolPolicy(scoped=False, no_commit=True),
        act=[
            {"write": str(elsewhere), "content": "notes\n"},
            {"write": str(in_specs), "content": "- [ ] 1.1\n"},
            {"terminal": "git", "args": ["commit", "-am", "wip"]},
            {"terminal": "git", "args": ["push", "origin", BRANCH]},
        ],
    )

    assert elsewhere.read_text() == "notes\n", "outside the worktree is the person's to change"
    assert in_specs.read_text() == "- [ ] 1.1\n", "and so are the specs"
    first, second = _did(record, "write")
    committed, pushed = _did(record, "terminal")
    assert "error" not in first and "error" not in second
    for refused in (committed, pushed):
        assert "error" in refused or refused.get("exitCode") != 0, refused
    assert git(worktree, "rev-parse", "HEAD") == before
