"""The conflict resolver's calls are labelled `restack`, in the request and in the ledger
(spec: roles, every call names its role)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.installation import Installation
from tests.call_rows import agent_rows
from tests.conftest import make_installation
from tests.pipeline.test_restack_conflict_rows import Spending, conflicting, move


def test_a_resolver_call_is_a_restack_call_in_the_request_and_the_row(
    tmp_path: Path, workspace: Installation
) -> None:
    runtime = Spending()

    move(conflicting(tmp_path / "repo"), runtime)

    assert [request.role for request in runtime.requests] == ["restack"]
    (row,) = agent_rows(workspace)
    assert (row["node"], row["role"]) == ("restack", "restack")


def test_the_resolver_runs_on_the_restack_model_the_configuration_names(
    tmp_path: Path,
) -> None:
    make_installation(tmp_path / "inst", models={"restack": "chosen-model"})
    runtime = Spending()

    move(conflicting(tmp_path / "repo"), runtime)

    assert runtime.requests[0].model == "chosen-model"


def test_the_resolver_defaults_to_the_cheap_model_under_claude_code(tmp_path: Path) -> None:
    make_installation(tmp_path / "inst")
    runtime = Spending()

    move(conflicting(tmp_path / "repo"), runtime)

    assert runtime.requests[0].model == "haiku"
