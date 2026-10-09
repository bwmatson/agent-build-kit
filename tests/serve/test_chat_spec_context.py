"""The unit's own session is told its change, and flags a request that contradicts it before
editing. A free session is told nothing of the kind.

The agent is the `claude` binary faked at its stream-json boundary; the worktree is a real
git worktree. The change is written where the planning repo keeps it. See
`tests/chat_serving.py` for the endpoints.

The flag is a fenced block in the agent's reply, which the server turns into a custom event:

    ```spec-conflict
    {"requirement": "<the requirement or task named>", "reason": "<how the request contradicts it>"}
    ```

    {"type": "CUSTOM", "name": "spec_conflict", "value": {"requirement": ..., "reason": ...}}
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from agent_build_kit import runtimes
from agent_build_kit.installation import Installation
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime
from tests.attach_driver import changed_files, checked_out, head
from tests.chat_serving import claude_session_file, record_session, turn, use_claude
from tests.runtimes.claude_cli import FakeClaude, finished_build, replied
from tests.serving import seed_pipeline

pytestmark = pytest.mark.serial

BUILD_SESSION = "0b7e1d52-9c3a-4f8e-b1d6-2a5c7e9f0d51"
FREE_SESSION = "6d2a8f14-3e5b-4c7a-9f0e-1b8d3c6a2e61"
REVIEW = "/api/units/feature/2"
UNIT = "feature/2"

PROPOSAL = "Sessions are kept in one registry so that a restart finds every one of them."
DESIGN = "The registry is written through a journal, never in place."
SPEC = "The system SHALL write the registry through its journal and never edit it in place."
GROUP = "Journal the registry writes"
CONTEXT = {
    "proposal": PROPOSAL,
    "design": DESIGN,
    "spec delta": SPEC,
    "task group": GROUP,
}

REQUIREMENT = "The registry is written through its journal"
REASON = "The request writes the registry file directly."
FLAG = (
    "This contradicts a requirement of the change.\n\n"
    "```spec-conflict\n"
    f"{json.dumps({'requirement': REQUIREMENT, 'reason': REASON})}\n"
    "```\n"
)


def write_change(inst: Installation) -> None:
    """The unit's change as the planning repo keeps it: its files are what a turn is given."""
    change = inst.changes_dir / "feature"
    (change / "specs" / "registry").mkdir(parents=True)
    (change / "proposal.md").write_text(f"## Why\n\n{PROPOSAL}\n")
    (change / "design.md").write_text(f"# Design\n\n{DESIGN}\n")
    (change / "specs" / "registry" / "spec.md").write_text(
        "## ADDED Requirements\n\n"
        f"### Requirement: {REQUIREMENT}\n\n{SPEC}\n\n"
        "#### Scenario: A restart\n\n- **WHEN** it restarts\n- **THEN** every session is found\n"
    )
    (change / "tasks.md").write_text(
        f"# Tasks\n\n## 1. [app] [tier1] {GROUP}\n\n- [ ] 1.1 Test: the journal is read\n"
        "\n## 2. [app] [tier1] A later group\n\n- [ ] 2.1 Test: nothing\n"
    )


@pytest.fixture
def tree(inst: Installation) -> Path:
    seed_pipeline(inst)
    write_change(inst)
    record_session(inst, UNIT, BUILD_SESSION, runtime="claude_code", model="opus")
    return checked_out(inst, UNIT)


def everything_sent(argv: list[str]) -> str:
    """The whole command line of a turn: the context may ride in the prompt or beside it."""
    return "\n".join(argv)


# --- what a turn is given -----------------------------------------------------------------------


def test_only_the_units_own_session_is_given_its_change_and_the_tests_with_code_rule(
    inst: Installation, tree: Path, api: httpx.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = use_claude(monkeypatch, replied(tree, "Looked."))

    turn(api, f"{REVIEW}/chat", {"tab": "t1", "prompt": "Add a note."})
    turn(api, f"{REVIEW}/chat", {"tab": "t1", "prompt": "And another."})

    assert len(fake.calls) == 2
    for argv, _ in fake.calls:
        sent = everything_sent(argv)
        for name, text in CONTEXT.items():
            assert text in sent, f"the {name} is part of every turn"
        assert "read-only" in sent.lower(), "the change is context, not something to edit"
        assert "together" in sent.lower(), "tests and code change together"

    from agent_build_kit.settings import settings

    assert settings.claude_home is not None
    claude_session_file(settings.claude_home, FREE_SESSION, tree)
    turn(
        api,
        f"/api/sessions/claude_code/{FREE_SESSION}/continue",
        {"tab": "t1", "prompt": "Change the notes."},
    )
    turn(
        api,
        "/api/sessions",
        {"tab": "t1", "runtime": "claude_code", "unit": UNIT, "prompt": "Look around."},
    )

    assert len(fake.calls) == 4
    for argv, _ in fake.calls[2:]:
        sent = everything_sent(argv)
        for name, text in CONTEXT.items():
            assert text not in sent, f"no {name} for a session that is not the unit's"
        assert "together" not in sent.lower()


# --- a request against a requirement ------------------------------------------------------------


def test_a_request_against_a_requirement_is_flagged_and_edits_nothing(
    inst: Installation, tree: Path, api: httpx.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = use_claude(monkeypatch, replied(tree, FLAG))
    before = head(tree)

    events = turn(
        api, f"{REVIEW}/chat", {"tab": "t1", "prompt": "Write the registry file directly."}
    )

    flags = [e for e in events if e["type"] == "CUSTOM" and e["name"] == "spec_conflict"]
    assert [f["value"] for f in flags] == [{"requirement": REQUIREMENT, "reason": REASON}]
    assert events.index(flags[0]) < next(
        i for i, e in enumerate(events) if e["type"] == "RUN_FINISHED"
    )
    assert "flag" in everything_sent(fake.calls[0][0]).lower(), "the agent was told to flag"
    assert changed_files(tree) == []
    assert head(tree) == before


# --- proceeding anyway --------------------------------------------------------------------------


class FlagThenEdit(FakeClaude):
    """A `claude` that flags the first turn and edits the worktree on the next."""

    def __init__(self, tree: Path) -> None:
        super().__init__(stdout=replied(tree, FLAG))
        self.tree = tree

    def __call__(self, argv, **kwargs):  # type: ignore[no-untyped-def]
        if self.calls:
            (self.tree / "notes.txt").write_text("a change\n")
            self.stdout = finished_build(self.tree, "Done.")
        return super().__call__(argv, **kwargs)


def test_proceeding_after_a_flag_is_a_builder_turn_on_the_same_session_that_edits(
    inst: Installation, tree: Path, api: httpx.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FlagThenEdit(tree)
    runtimes.names()
    monkeypatch.setitem(runtimes._REGISTRY, "claude_code", ClaudeCodeRuntime(execute=fake))
    before = head(tree)

    flagged = turn(api, f"{REVIEW}/chat", {"tab": "t1", "prompt": "Write the file directly."})
    assert [e for e in flagged if e["type"] == "CUSTOM" and e["name"] == "spec_conflict"]
    assert changed_files(tree) == []

    turn(api, f"{REVIEW}/chat", {"tab": "t1", "prompt": "Proceed anyway."})

    argv, _ = fake.calls[1]
    sent = everything_sent(argv)
    for name, text in CONTEXT.items():
        assert text in sent, f"the {name} is still part of the turn"
    assert "--specs" in sent, "the builder's policy"
    assert BUILD_SESSION in sent, "the unit's own session"
    assert changed_files(tree) == ["notes.txt"]
    assert head(tree) == before


# --- changing the spec instead ------------------------------------------------------------------


def test_changing_the_spec_opens_a_free_session_on_the_planning_repo_with_the_flag(
    inst: Installation, tree: Path, api: httpx.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = use_claude(monkeypatch, replied(inst.root, "Looking at the spec."))
    first_message = f"{REQUIREMENT}: {REASON}"

    turn(
        api,
        "/api/sessions",
        {"tab": "t1", "runtime": "claude_code", "repo": "planning", "prompt": first_message},
    )

    argv, cwd = fake.calls[0]
    assert cwd == inst.root
    assert first_message in everything_sent(argv)
    for name, text in CONTEXT.items():
        assert text not in everything_sent(argv), f"a free session has no {name}"
