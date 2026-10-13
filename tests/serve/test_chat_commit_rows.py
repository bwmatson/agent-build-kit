"""The attach flow's fix turn is in the ledger as `chat_commit`, naming the unit being committed
with its change, repository and tier and the recorded builder's model (spec: usage-accounting,
every agent call writes exactly one row).

The agent is the `claude` binary faked at its stream-json boundary, as in `test_chat_commit.py`.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_store import UnitStore
from tests.attach_driver import checked_out
from tests.call_rows import agent_rows
from tests.chat_serving import record_session
from tests.serve.test_chat_commit import (
    BUILD_SESSION,
    UNIT,
    chat_edit,
    commit,
    pre_commit,
    scripted,
)
from tests.serving import seed_pipeline

pytestmark = pytest.mark.serial


@pytest.fixture
def tree(inst: Installation) -> Path:
    seed_pipeline(inst)
    record_session(inst, UNIT, BUILD_SESSION, runtime="claude_code", model="opus")
    return checked_out(inst, UNIT)


def test_the_fix_turn_writes_a_chat_commit_row_beside_the_chat_turn(
    inst: Installation, tree: Path, api: httpx.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    scripted(monkeypatch, tree, {"notes.txt": "BAD word\n"}, {"notes.txt": "fine\n"})
    chat_edit(api)
    pre_commit(
        tree,
        'if grep -q BAD notes.txt; then echo "lint: BAD word in notes.txt" >&2; exit 1; fi\n'
        "exit 0\n",
    )

    assert commit(api).status_code == 200

    stored = UnitStore(inst.state_dir / "units.json").get(UNIT)
    chat, fix = agent_rows(inst)
    assert chat["node"] == "chat"
    assert (fix["node"], fix["unit"], fix["change"], fix["repo"], fix["tier"]) == (
        "chat_commit",
        UNIT,
        stored.change,
        stored.repo,
        stored.tier,
    )
    assert (fix["role"], fix["model"], fix["outcome"]) == ("generic", "opus", "ok")
