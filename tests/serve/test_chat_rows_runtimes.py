"""A chat turn and the attach flow's fix turn each write exactly one row under both runtimes: the
Claude runtime over a faked `claude` process and the ACP runtime over a small agent speaking the
protocol on stdio (spec: usage-accounting, every agent call writes exactly one row).

The other sites of the audit run over both runtimes in `tests/test_agent_call_rows.py`; these
need the server and a unit, so they sit with the chat tests.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.lease import Leases, lease_dir
from tests.attach_driver import checked_out
from tests.call_rows import agent_rows
from tests.chat_serving import record_session, turn, unit_worktree, use_claude
from tests.runtimes.acp_agent import SESSION as ACP_SESSION
from tests.runtimes.acp_agent import use_agent
from tests.runtimes.claude_cli import finished_build
from tests.serve.test_chat_commit import ScriptedClaude, commit, pre_commit
from tests.serving import seed_pipeline

CLAUDE = "claude_code"
ACP = "acp"
UNIT = "feature/2"
REVIEW = "/api/units/feature/2"


@pytest.fixture
def pipeline(inst: Installation) -> Installation:
    seed_pipeline(inst)
    return inst


@pytest.mark.parametrize("kind", [CLAUDE, ACP])
def test_a_chat_turn_writes_exactly_one_chat_row(
    pipeline: Installation,
    api: httpx.Client,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    build_session: str,
) -> None:
    if kind == CLAUDE:
        record_session(pipeline, UNIT, build_session, runtime=CLAUDE)
        use_claude(monkeypatch, finished_build(unit_worktree(pipeline, UNIT), "Hello."))
    else:
        record_session(pipeline, UNIT, ACP_SESSION, runtime=ACP)
        unit_worktree(pipeline, UNIT)
        use_agent(
            tmp_path / "agent.jsonl", resume=True, list_sessions=True, sessions=(ACP_SESSION,)
        )

    turn(api, f"{REVIEW}/chat", {"tab": "t1", "prompt": "Why this approach?"})

    rows = agent_rows(pipeline)
    assert [(row["node"], row["unit"], row["runtime"]) for row in rows] == [("chat", UNIT, kind)]


@pytest.mark.parametrize("kind", [CLAUDE, ACP])
def test_a_fix_turn_writes_exactly_one_chat_commit_row(
    pipeline: Installation,
    api: httpx.Client,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    build_session: str,
) -> None:
    tree = checked_out(pipeline, UNIT)
    (tree / "notes.txt").write_text("BAD word\n")
    pre_commit(
        tree,
        'if grep -q BAD notes.txt; then echo "lint: BAD word in notes.txt" >&2; exit 1; fi\n'
        "exit 0\n",
    )
    session = build_session if kind == CLAUDE else ACP_SESSION
    assert Leases(lease_dir(pipeline.state_dir)).take(
        UNIT, "tab:t1", checkouts=("worktree",), session=session, runtime=kind, head="abc"
    )
    if kind == CLAUDE:
        fake = ScriptedClaude(finished_build(tree, "Fixed."), {"notes.txt": "fine\n"})
        use_claude(monkeypatch, "", fake)
    else:
        use_agent(
            tmp_path / "agent.jsonl",
            resume=True,
            list_sessions=True,
            sessions=(ACP_SESSION,),
            act=[{"edit": str(tree / "notes.txt"), "content": "fine\n"}],
        )

    answer = commit(api, checkouts=["worktree"])

    assert answer.status_code == 200
    rows = agent_rows(pipeline)
    assert [(row["node"], row["unit"], row["runtime"]) for row in rows] == [
        ("chat_commit", UNIT, kind)
    ]
