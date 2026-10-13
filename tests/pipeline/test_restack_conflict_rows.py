"""The conflict resolver's calls are in the ledger, one `restack` row per call naming the unit
being moved (spec: usage-accounting, every agent call writes exactly one row).

The resolver runs through a runtime that reports what it spent, as every runtime hands the
finished result to the request's `on_result`; the ledger is read back from disk.
"""

from __future__ import annotations

import json
from functools import partial
from pathlib import Path

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import restack
from agent_build_kit.pipeline.usage_guard import RateLimited
from agent_build_kit.pipeline.usage_ledger import LEDGER_NAME
from agent_build_kit.runtimes import AgentRequest, AgentResult
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime
from agent_build_kit.usage import Usage
from tests.factories import git, init_repo
from tests.pipeline.test_restack_conflicts import commit
from tests.runtimes.claude_cli import FakeClaude, refused
from tests.runtimes.stand_in import StandInRuntime

UNIT = "add-marker/2"


class Spending(StandInRuntime):
    """A runtime whose every call resolves the conflict and reports tokens, cost and duration."""

    name = "spending"

    def run(self, request: AgentRequest) -> AgentResult:
        self.requests.append(request)
        assert request.cwd is not None
        (request.cwd / "markers.py").write_text('markers = ["integration", "local_stack"]\n')
        result = AgentResult(
            ok=True,
            text="resolved",
            usage=Usage(input_tokens=1200, output_tokens=300),
            cost_usd=0.31,
            duration_ms=42_000,
            usage_source="reported",
        )
        if request.on_result:
            request.on_result(result)
        return result


def conflicting(path: Path) -> Path:
    """main and spec/c/2 both change markers.py, in different ways."""
    repo = init_repo(path)
    commit(repo, "markers.py", "markers = []\n")
    git(repo, "checkout", "-q", "-b", "spec/c/1")
    git(repo, "checkout", "-q", "-b", "spec/c/2")
    commit(repo, "markers.py", 'markers = ["local_stack"]\n')
    git(repo, "checkout", "-q", "main")
    commit(repo, "markers.py", 'markers = ["integration"]\n')
    return repo


def clean(path: Path) -> Path:
    """main and spec/c/2 change different files."""
    repo = init_repo(path)
    commit(repo, "markers.py", "markers = []\n")
    git(repo, "checkout", "-q", "-b", "spec/c/1")
    git(repo, "checkout", "-q", "-b", "spec/c/2")
    commit(repo, "local.py", "local = 1\n")
    git(repo, "checkout", "-q", "main")
    commit(repo, "other.py", "other = 1\n")
    return repo


def move(repo: Path, runtime) -> restack.Moved:
    return restack.resolved_move(
        repo,
        "spec/c/2",
        new_base="main",
        old_base="spec/c/1",
        moving_unit=UNIT,
        moving_change="add-marker",
        moving_repo="app",
        moving_intent="Register the local_stack marker in app",
        onto_unit="add-integration/1",
        onto_intent="Register the integration marker in app",
        resolve=partial(restack.claude_resolver, runtime=runtime),
    )


def rows(workspace: Installation) -> list[dict]:
    path = workspace.state_dir / LEDGER_NAME
    lines = path.read_text().splitlines() if path.exists() else []
    return [json.loads(line) for line in lines]


def test_a_conflicting_restack_writes_one_restack_row_naming_the_unit_being_moved(
    tmp_path: Path, workspace: Installation
) -> None:
    move(conflicting(tmp_path / "repo"), Spending())

    (row,) = rows(workspace)
    assert (row["node"], row["unit"], row["role"]) == ("restack", UNIT, "generic")
    assert (row["change"], row["repo"]) == ("add-marker", "app")
    assert row["runtime"] == "spending"
    assert row["input_tokens"] == 1200
    assert row["output_tokens"] == 300
    assert row["cost"]["incremental_usd"] == pytest.approx(0.31)
    assert row["duration_ms"] == 42_000
    assert row["outcome"] == "ok"


def test_a_second_conflict_for_the_unit_is_a_second_row_and_a_clean_restack_is_none(
    tmp_path: Path, workspace: Installation
) -> None:
    runtime = Spending()

    move(clean(tmp_path / "clean"), runtime)
    assert runtime.requests == []
    move(conflicting(tmp_path / "first"), runtime)
    move(conflicting(tmp_path / "second"), runtime)

    written = rows(workspace)
    assert [(r["node"], r["unit"]) for r in written] == [("restack", UNIT)] * 2


def test_a_resolver_refused_for_the_usage_limit_has_written_its_failed_row_first(
    tmp_path: Path, workspace: Installation
) -> None:
    repo = conflicting(tmp_path / "repo")
    before = git(repo, "rev-parse", "spec/c/2")
    fake = FakeClaude(
        stdout=refused(repo, "Claude AI usage limit reached|1919763200"), returncode=1
    )

    with pytest.raises(RateLimited):
        move(repo, ClaudeCodeRuntime(execute=fake))

    (row,) = rows(workspace)
    assert (row["node"], row["unit"], row["outcome"]) == ("restack", UNIT, "failed")
    assert not (repo / ".git" / "rebase-merge").exists()
    assert git(repo, "rev-parse", "spec/c/2") == before
