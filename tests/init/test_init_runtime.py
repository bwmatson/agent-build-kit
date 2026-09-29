"""`abk init`'s research and propose steps reach their agent through the
runtime seam.

They used to hand an argv of their own to a shared executor. Now each sends a
request, and under Claude Code the command that reaches the CLI carries the
tool lists and the settings each carried before: research reads and searches
the web and writes nothing, a proposal runs in the planning repo, reads the
code repo, and carries the policy hook with no read-only specs directory. A
refusal is a rate limit, as it is everywhere else.
"""

from __future__ import annotations

import json
import subprocess
from datetime import date
from pathlib import Path

import pytest

from agent_build_kit.init.propose import propose
from agent_build_kit.init.research import research
from agent_build_kit.pipeline.usage_guard import RateLimited
from agent_build_kit.runtimes import AgentRequest
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime
from tests.init.test_propose import detection, valid_report, write_change
from tests.runtimes.claude_cli import FakeClaude
from tests.runtimes.stand_in import StandInRuntime
from tests.runtimes.test_claude_code_argv import (
    DENIED,
    PROPOSE_TOOLS,
    RESEARCH_TOOLS,
    flags,
    hook,
)

TODAY = date(2030, 1, 2)
DOCUMENT = "## Formatting\n\n- ruff format\n\n## Sources\n\n- https://example.invalid/ruff\n"


@pytest.fixture
def planning(tmp_path: Path) -> Path:
    root = tmp_path / "planning"
    (root / "openspec" / "changes").mkdir(parents=True)
    (root / "docs" / "recommendations").mkdir(parents=True)
    (root / "docs" / "recommendations" / "python.md").write_text("## Linting\n\n- ruff\n")
    return root


@pytest.fixture
def app(tmp_path: Path) -> Path:
    repo = tmp_path / "app"
    repo.mkdir()
    (repo / "pyproject.toml").write_text('[project]\nname = "app"\n')
    return repo


# --- research ---------------------------------------------------------------------


def test_research_runs_through_the_runtime_it_is_given(tmp_path: Path) -> None:
    runtime = StandInRuntime(answer=DOCUMENT)

    path = research(
        "python", built_in="seed", output=tmp_path / "python.md", runtime=runtime, today=TODAY
    )

    assert path.read_text().endswith(DOCUMENT)
    request = runtime.request
    assert "as of 2030-01-02" in request.prompt
    assert request.allowed_tools == RESEARCH_TOOLS
    assert request.permission_mode == "allowed_tools_only"
    assert request.policy is None


def test_under_claude_code_research_sends_the_command_it_sent_before(tmp_path: Path) -> None:
    fake = FakeClaude(stdout=DOCUMENT)

    path = research(
        "python",
        built_in="seed",
        output=tmp_path / "python.md",
        runtime=ClaudeCodeRuntime(execute=fake),
        today=TODAY,
    )

    prompt = fake.argv[fake.argv.index("-p") + 1]
    assert flags(fake.argv, prompt) == {
        "-p": None,
        "--allowedTools": RESEARCH_TOOLS,
        "--output-format": "text",
    }
    assert path.read_text().endswith(DOCUMENT)


def test_refused_research_is_a_rate_limit_and_writes_nothing(tmp_path: Path) -> None:
    fake = FakeClaude(stdout="Claude AI usage limit reached|1919763200\n", returncode=1)

    with pytest.raises(RateLimited) as caught:
        research(
            "python",
            built_in="seed",
            output=tmp_path / "python.md",
            runtime=ClaudeCodeRuntime(execute=fake),
            today=TODAY,
        )

    assert caught.value.resets_at is not None
    assert caught.value.resets_at.year == 2030
    assert not (tmp_path / "python.md").exists()


def test_failed_research_writes_no_document(tmp_path: Path) -> None:
    """A run that broke leaves nothing that reads as recommendations."""
    runtime = StandInRuntime(ok=False, answer="## Formatting\n", error="claude exited 1: broken")

    with pytest.raises(Exception, match="broken"):
        research(
            "python", built_in="seed", output=tmp_path / "python.md", runtime=runtime, today=TODAY
        )

    assert not (tmp_path / "python.md").exists()


def test_with_no_runtime_given_research_uses_the_active_one(tmp_path: Path) -> None:
    with pytest.raises(AssertionError, match="inject `execute=`"):
        research("python", built_in="seed", output=tmp_path / "python.md", today=TODAY)


# --- propose ----------------------------------------------------------------------


class WritesTheChange(FakeClaude):
    """The CLI, having written the change into the planning repo it ran in."""

    def __call__(self, argv, *, cwd=None, on_event=None) -> subprocess.CompletedProcess[str]:
        assert cwd is not None
        write_change(cwd, "app-testing-infrastructure")
        return super().__call__(argv, cwd=cwd, on_event=on_event)


def _propose(planning: Path, app: Path, **kwargs) -> str:
    return propose(
        "app",
        detection(app),
        planning=planning,
        recommendations=planning / "docs" / "recommendations" / "python.md",
        kind="testing-infrastructure",
        run_openspec=valid_report(planning),
        repos=("platform", "app"),
        **kwargs,
    )


def test_propose_runs_through_the_runtime_it_is_given(planning: Path, app: Path) -> None:
    def writes_the_change(request: AgentRequest) -> None:
        assert request.cwd is not None
        write_change(request.cwd, "app-testing-infrastructure")

    runtime = StandInRuntime(act=writes_the_change)

    assert _propose(planning, app, runtime=runtime) == "app-testing-infrastructure"

    request = runtime.request
    assert request.cwd == planning
    assert request.add_dirs == (app,)
    assert request.allowed_tools == PROPOSE_TOOLS
    assert request.permission_mode == "edit"
    # The hook, with writes into openspec/ allowed: that is the step's job.
    assert request.policy is not None
    assert request.policy.specs_dir is None


def test_under_claude_code_propose_sends_the_command_it_sent_before(
    planning: Path, app: Path
) -> None:
    """The settings and tool list it carried before, plus the deny list that
    now comes with every policed run."""
    fake = WritesTheChange(stdout="Wrote the change.")

    _propose(planning, app, runtime=ClaudeCodeRuntime(execute=fake))

    prompt = fake.argv[fake.argv.index("-p") + 1]
    carried = flags(fake.argv, prompt)
    assert json.loads(carried.pop("--settings") or "") == hook(None)
    assert carried == {
        "-p": None,
        "--add-dir": str(app),
        "--allowedTools": PROPOSE_TOOLS,
        "--disallowedTools": DENIED,
        "--permission-mode": "acceptEdits",
        "--output-format": "text",
    }
    assert fake.calls[0][1] == planning


def test_a_refused_proposal_is_a_rate_limit_without_a_repair_round(
    planning: Path, app: Path
) -> None:
    """A refusal is not a change that failed validation: nothing is retried."""
    fake = FakeClaude(stdout="Claude AI usage limit reached|1919763200\n", returncode=1)

    with pytest.raises(RateLimited) as caught:
        _propose(planning, app, runtime=ClaudeCodeRuntime(execute=fake))

    assert caught.value.resets_at is not None
    assert caught.value.resets_at.year == 2030
    assert len(fake.calls) == 1


def test_with_no_runtime_given_propose_uses_the_active_one(planning: Path, app: Path) -> None:
    with pytest.raises(AssertionError, match="inject `execute=`"):
        _propose(planning, app)
