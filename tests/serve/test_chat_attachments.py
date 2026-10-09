"""A turn's attachments are put into the prompt both runtimes receive.

An attachment is a file, a line range, the diff hunk and the selected text. The agents are
faked at their wires, as in the other chat tests; the composer's chips are the web UI's
(`web/src/composer.test.tsx`).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import httpx
import pytest

from agent_build_kit.installation import Installation
from tests.chat_serving import prompt_of, record_session, turn, unit_worktree, use_claude
from tests.runtimes.acp_agent import SESSION as ACP_SESSION
from tests.runtimes.acp_agent import requests, use_agent
from tests.runtimes.claude_cli import finished_build
from tests.serving import seed_pipeline

# A session id on a command line (an editor holding it, a fake agent listing it) is seen by
# every server on the machine, so these cannot run beside each other.
pytestmark = pytest.mark.serial

CHAT = "/api/units/feature/2/chat"
CLAUDE_SESSION = "0b7e1d52-9c3a-4f8e-b1d6-2a5c7e9f0d32"

MARKER = {
    "file": "src/app/marker.py",
    "lines": [3, 5],
    "hunk": "@@ -3,3 +3,3 @@\n-MARKER = None\n+MARKER = 'added'\n context_line",
    "text": "MARKER = 'added'",
}
OTHER = {
    "file": "src/app/other.py",
    "lines": [10, 12],
    "hunk": "@@ -10,3 +10,3 @@\n-OTHER = 1\n+OTHER = 2\n other_context",
    "text": "OTHER = 2",
}


@pytest.fixture
def pipeline(inst: Installation) -> Installation:
    seed_pipeline(inst)
    unit_worktree(inst, "feature/2")
    return inst


def claude_prompt(
    inst: Installation, api: httpx.Client, monkeypatch: pytest.MonkeyPatch, attachments: list[Any]
) -> str:
    record_session(inst, "feature/2", CLAUDE_SESSION, runtime="claude_code")
    fake = use_claude(monkeypatch, finished_build(unit_worktree(inst, "feature/2"), "Ok."))
    turn(api, CHAT, {"tab": "t1", "prompt": "Why this change?", "attachments": attachments})
    return prompt_of(fake.calls[0][0])


def acp_prompt(
    inst: Installation, api: httpx.Client, tmp_path: Path, attachments: list[Any]
) -> str:
    record_session(inst, "feature/2", ACP_SESSION, runtime="acp")
    record = tmp_path / "agent.jsonl"
    use_agent(record, resume=True, list_sessions=True, sessions=(ACP_SESSION,))
    turn(api, CHAT, {"tab": "t1", "prompt": "Why this change?", "attachments": attachments})
    [prompted] = requests(record, "session/prompt")
    return " ".join(str(block.get("text", "")) for block in prompted["prompt"])


def test_the_prompt_sent_to_claude_contains_the_attachment(
    pipeline: Installation, api: httpx.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    prompt = claude_prompt(pipeline, api, monkeypatch, [MARKER])

    assert "Why this change?" in prompt
    assert "src/app/marker.py" in prompt
    assert re.search(r"3\D+5", prompt), "the line range"
    assert MARKER["hunk"] in prompt
    assert MARKER["text"] in prompt


def test_the_prompt_sent_to_the_acp_agent_contains_the_attachment(
    pipeline: Installation, api: httpx.Client, tmp_path: Path
) -> None:
    prompt = acp_prompt(pipeline, api, tmp_path, [MARKER])

    assert "Why this change?" in prompt
    assert "src/app/marker.py" in prompt
    assert re.search(r"3\D+5", prompt), "the line range"
    assert MARKER["hunk"] in prompt
    assert MARKER["text"] in prompt


def test_every_attachment_of_a_turn_is_in_the_prompt(
    pipeline: Installation, api: httpx.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    prompt = claude_prompt(pipeline, api, monkeypatch, [MARKER, OTHER])

    assert MARKER["text"] in prompt and OTHER["text"] in prompt


def test_an_attachment_removed_before_sending_is_not_in_the_prompt(
    pipeline: Installation, api: httpx.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    prompt = claude_prompt(pipeline, api, monkeypatch, [OTHER])

    assert "src/app/marker.py" not in prompt
    assert MARKER["text"] not in prompt
    assert OTHER["text"] in prompt


def test_a_turn_without_attachments_is_its_prompt_alone(
    pipeline: Installation, api: httpx.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    prompt = claude_prompt(pipeline, api, monkeypatch, [])

    assert "Why this change?" in prompt
    assert "@@" not in prompt


def test_an_attachment_of_uncommitted_lines_is_marked_uncommitted_in_the_prompt(
    pipeline: Installation, api: httpx.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    prompt = claude_prompt(pipeline, api, monkeypatch, [{**MARKER, "uncommitted": True}])

    assert MARKER["text"] in prompt
    assert "uncommitted" in prompt.lower()


def test_an_attachment_of_committed_lines_is_not_marked_uncommitted(
    pipeline: Installation, api: httpx.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    prompt = claude_prompt(pipeline, api, monkeypatch, [MARKER])

    assert "uncommitted" not in prompt.lower()


def test_only_the_uncommitted_attachment_of_a_turn_carries_the_marker(
    pipeline: Installation, api: httpx.Client, tmp_path: Path
) -> None:
    prompt = acp_prompt(pipeline, api, tmp_path, [MARKER, {**OTHER, "uncommitted": True}])

    assert prompt.lower().count("uncommitted") == 1
    assert prompt.lower().index("uncommitted") > prompt.index(MARKER["text"])
