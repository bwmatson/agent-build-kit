"""A call's ledger row carries the key of the account it ran on (spec: claude-accounts, each
call runs on the right account).

The row is written through the helper every agent call uses, from the request's account.
"""

import json
from pathlib import Path

from agent_build_kit.claude_account import Account
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.call_record import recorded
from agent_build_kit.pipeline.usage_ledger import LEDGER_NAME
from agent_build_kit.runtimes import AgentRequest, AgentResult
from tests.runtimes.stand_in import StandInRuntime


def written(workspace: Installation, account: Account | None) -> dict:
    request = AgentRequest(prompt="build it", role="generic", model="m-1", account=account)
    request = recorded(request, StandInRuntime(), node="implement", unit="add-marker/1", say=print)
    assert request.on_result is not None
    request.on_result(AgentResult(ok=True, text="done"))
    (line,) = (workspace.state_dir / LEDGER_NAME).read_text().splitlines()
    return json.loads(line)


def test_a_labelled_accounts_row_carries_its_directory(
    workspace: Installation,
) -> None:
    account = Account(label="kit", config_dir=Path("/accounts/kit"))

    assert written(workspace, account)["account"] == "/accounts/kit"
