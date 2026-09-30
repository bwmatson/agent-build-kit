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

import json
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.pipeline.command_policy import check_command
from agent_build_kit.runtimes import AgentRequest, ToolPolicy
from agent_build_kit.runtimes.acp import AcpRuntime
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
