"""A round posts again the replies a unit in review still owes, from its thread."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.forges import RepoId
from agent_build_kit.graph.checkpointer import open_checkpointer, unit_graphs_path
from agent_build_kit.graph.state import Node, UnitRun
from agent_build_kit.graph.unit import seed_thread
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.pr_replies import build_post_replies, parse_answer
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW
from agent_build_kit.pipeline.workspaces import branch_lock
from tests.conftest import make_installation
from tests.factories import stored_unit
from tests.forges.stand_in import StandInForge, lookup

ID = "one/1"
BRANCH = "spec/one/1"
ANSWER = json.dumps({"replies": [{"comment_id": 11, "body": "Now a frozen model."}], "summary": ""})


class Refusing(StandInForge):
    def post_reply(self, repo: RepoId, pr: int, *, note_id: str, body: str) -> list[str]:
        return []


@pytest.fixture
def inst(tmp_path: Path) -> Installation:
    installation = make_installation(
        tmp_path, planning=dict(state_dir=".", worktree_root=str(tmp_path.parent / "trees"))
    )
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored_unit(ID, change="one")])
    store.set_state(ID, IN_REVIEW, pr=5, branch=BRANCH)

    async def seed() -> None:
        async with open_checkpointer(unit_graphs_path(installation.state_dir)) as saver:
            state = UnitRun(
                unit_id=ID, change="one", pending_replies=(ANSWER,), head="0123456789ab"
            )
            await seed_thread(saver, state, as_node=Node.AWAIT_REVIEW)

    asyncio.run(seed())
    return installation


def owed(inst: Installation) -> tuple[str, ...]:
    state = cli.thread_of(inst, ID).state
    assert state is not None
    return state.pending_replies


def round_with(inst: Installation, tmp_path: Path, forge: StandInForge) -> None:
    reply = build_post_replies(root=tmp_path, for_repo=lookup(forge), log=lambda line: None)
    cli.retry_replies(inst, UnitStore(tmp_path / "units.json"), reply=reply)


def test_a_round_posts_an_owed_reply_once_and_clears_it_from_the_thread(
    inst: Installation, tmp_path: Path
) -> None:
    host = StandInForge()

    round_with(inst, tmp_path, host)
    assert [note for note, _ in host.replies] == ["11"]
    assert owed(inst) == ()

    round_with(inst, tmp_path, host)
    assert [note for note, _ in host.replies] == ["11"], "a second round posts nothing"


def test_a_round_against_a_refusing_host_leaves_the_owed_reply_as_it_was(
    inst: Installation, tmp_path: Path
) -> None:
    before = owed(inst)

    round_with(inst, tmp_path, Refusing())

    (left,) = owed(inst)
    now, then = parse_answer(left), parse_answer(before[0])
    assert now is not None and then is not None
    assert now.replies == then.replies


def test_a_unit_whose_branch_is_held_is_left_for_the_next_round(
    inst: Installation, tmp_path: Path
) -> None:
    host = StandInForge()

    with branch_lock(BRANCH, root=inst.state_dir / "locks"):
        round_with(inst, tmp_path, host)

    assert host.replies == []
    assert len(owed(inst)) == 1
