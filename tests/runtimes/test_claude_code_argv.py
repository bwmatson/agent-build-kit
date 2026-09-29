"""The Claude Code adapter builds the invocations the call sites build today.

Selecting the default runtime must change nothing observable, so each shape
the pipeline sends — a build, a review, a track phase, the planner's graph
call, research, a proposal and the restack resolver — is pinned here as the
flags and values it carries now: the readable specs directory, the policy hook
registered per run, the allowed and denied tools, the edit permission mode,
the model, and how the output comes back. Flag order is not asserted: the CLI
does not read it, and the three call sites never agreed on one.

The expected values are written out rather than imported from the modules
that build them today, which this change folds into the adapter.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from agent_build_kit import config, runtimes
from agent_build_kit.config import WorkspaceConfig
from agent_build_kit.runtimes import AgentRequest, ToolPolicy, claude_code
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime
from agent_build_kit.runtimes.claude_code import refresh_login as real_refresh_login
from tests.runtimes.claude_cli import FakeClaude, finished_build, stream

# What wiring.py passes as a build's tools today: its own list, then the
# python-uv profile's toolchain commands.
BUILD_TOOLS = (
    "Read Edit Write Grep Glob Bash(git *) Bash(gh pr view*) Bash(gh pr diff*) "
    "Bash(uv run *) Bash(pre-commit *)"
)
REVIEW_TOOLS = "Read Grep Glob Bash(git diff*) Bash(git log*) Bash(git show*)"
# init/research.py, init/propose.py and restack.claude_resolver's lists.
RESEARCH_TOOLS = "Read Grep Glob WebSearch WebFetch"
PROPOSE_TOOLS = "Read Grep Glob Write Edit Bash(ls*)"
RESOLVER_TOOLS = "Read Edit Write Grep Glob"
DENIED = (
    "Bash(gh pr merge*) Bash(git push --force *) Bash(git reset --hard*) "
    "Bash(rm -rf*) Bash(git branch -D*)"
)

BARE_FLAGS = {"-p", "--verbose"}


def flags(argv: list[str], prompt: str) -> dict[str, str | None]:
    """The flags an invocation carries and each one's value, the prompt aside."""
    assert argv[0] == "claude"
    assert argv.count(prompt) == 1, "the prompt is passed exactly once"
    rest = [token for token in argv[1:] if token != prompt]
    carried: dict[str, str | None] = {}
    tokens = iter(rest)
    for token in tokens:
        assert token.startswith("-"), f"{token!r} is not a flag"
        assert token not in carried, f"{token} is passed twice"
        carried[token] = None if token in BARE_FLAGS else next(tokens)
    return carried


def hook(specs: Path | None, *, branch_prefix: str = "spec/") -> dict:
    """The PreToolUse registration a policed run carries, naming the policy
    module under the interpreter abk itself runs on."""
    command = f"{sys.executable} -m agent_build_kit.hooks.policy --branch-prefix {branch_prefix}"
    if specs is not None:
        command += f" --specs {specs}"
    return {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash|Edit|Write|MultiEdit|NotebookEdit",
                    "hooks": [{"type": "command", "command": command, "args": []}],
                }
            ]
        }
    }


def _specs(root: Path) -> Path:
    return root / "planning" / "openspec" / "specs"


def _run(request: AgentRequest, fake: FakeClaude) -> list[str]:
    ClaudeCodeRuntime(execute=fake).run(request)
    return fake.argv


def test_the_default_runtime_is_registered_as_claude_code() -> None:
    """The name an abk.yaml written before this change implicitly selects."""
    runtime = runtimes.get("claude_code")

    assert runtime is claude_code.RUNTIME
    assert isinstance(runtime, ClaudeCodeRuntime)
    assert runtime.name == "claude_code"


def test_the_adapter_declares_what_it_can_do() -> None:
    """Every call reaches the hook before it runs, the usage window can be
    read, and progress is streamed."""
    runtime = ClaudeCodeRuntime(execute=FakeClaude())

    assert runtime.implemented is True
    assert runtime.policy_coverage == "all_calls"
    assert runtime.supports_usage_tracking is True
    assert runtime.supports_streaming is True


def test_a_build_carries_the_flags_it_carries_today(tmp_path: Path) -> None:
    specs = _specs(tmp_path)
    worktree = tmp_path / "worktrees" / "app"
    fake = FakeClaude(stdout=finished_build(worktree, "done"))
    request = AgentRequest(
        prompt="Implement group 1 of add-marker.",
        role="implement",
        cwd=worktree,
        add_dirs=(specs,),
        model="opus",
        allowed_tools=BUILD_TOOLS,
        permission_mode="edit",
        policy=ToolPolicy(specs_dir=specs, branch_prefix="spec/"),
        on_event=lambda line: None,
    )

    argv = _run(request, fake)
    carried = flags(argv, request.prompt)

    settings = carried.pop("--settings")
    assert settings is not None
    assert json.loads(settings) == hook(specs)
    assert carried == {
        "-p": None,
        "--add-dir": str(specs),
        "--allowedTools": BUILD_TOOLS,
        "--disallowedTools": DENIED,
        "--permission-mode": "acceptEdits",
        "--model": "opus",
        "--output-format": "stream-json",
        "--verbose": None,
    }
    assert fake.calls[0][1] == worktree


def test_a_review_carries_the_flags_it_carries_today(tmp_path: Path) -> None:
    """Read-only by its tool list, as today: the reviewer has no edit tool to
    call, and still carries the hook and the deny list beside it."""
    specs = _specs(tmp_path)
    worktree = tmp_path / "worktrees" / "app"
    fake = FakeClaude(stdout=finished_build(worktree, '{"approved": true}'))
    request = AgentRequest(
        prompt="Review the changes on this branch.",
        role="rework_review",
        cwd=worktree,
        add_dirs=(specs,),
        model="fable",
        allowed_tools=REVIEW_TOOLS,
        policy=ToolPolicy(specs_dir=specs),
        on_event=lambda line: None,
    )

    argv = _run(request, fake)
    carried = flags(argv, request.prompt)

    settings = carried.pop("--settings")
    assert settings is not None
    assert json.loads(settings) == hook(specs)
    assert carried == {
        "-p": None,
        "--add-dir": str(specs),
        "--allowedTools": REVIEW_TOOLS,
        "--disallowedTools": DENIED,
        "--permission-mode": "acceptEdits",
        "--model": "fable",
        "--output-format": "stream-json",
        "--verbose": None,
    }


def test_the_hook_scopes_its_rule_to_the_workspace_s_branch_prefix(tmp_path: Path) -> None:
    specs = _specs(tmp_path)
    fake = FakeClaude(stdout=finished_build(tmp_path, "done"))
    request = AgentRequest(
        prompt="Implement it.",
        cwd=tmp_path,
        add_dirs=(specs,),
        model="opus",
        allowed_tools=BUILD_TOOLS,
        policy=ToolPolicy(specs_dir=specs, branch_prefix="unit/"),
        on_event=lambda line: None,
    )

    carried = flags(_run(request, fake), request.prompt)

    assert json.loads(carried["--settings"] or "") == hook(specs, branch_prefix="unit/")


def test_a_track_phase_carries_the_flags_it_carries_today(tmp_path: Path) -> None:
    """A track names its own worktree, reads the planning repo for its run
    logs, takes its model and tools from the tracks configuration, and keeps
    the run's JSON record — with no hook, as today."""
    planning = tmp_path / "planning"
    checkout = tmp_path / "checkouts" / "app"
    record = json.dumps({"type": "result", "subtype": "success", "result": "ok"})
    fake = FakeClaude(stdout=record)
    request = AgentRequest(
        prompt="Run the health track for app.",
        cwd=checkout,
        add_dirs=(planning,),
        model="haiku",
        allowed_tools="Read",
        denied_tools="Bash(rm *)",
        worktree="abk-20260928T0300",
        keep_record=True,
    )

    argv = _run(request, fake)

    assert flags(argv, request.prompt) == {
        "-p": None,
        "--worktree": "abk-20260928T0300",
        "--add-dir": str(planning),
        "--permission-mode": "acceptEdits",
        "--allowedTools": "Read",
        "--disallowedTools": "Bash(rm *)",
        "--model": "haiku",
        "--output-format": "json",
    }
    assert fake.calls[0][1] == checkout


def test_a_run_with_no_policy_carries_no_hook_and_no_added_denies(tmp_path: Path) -> None:
    """The hook and the pipeline's deny list come with a policy, and only then:
    a track phase has never carried either."""
    fake = FakeClaude(stdout=stream({"type": "result", "result": "ok"}))
    request = AgentRequest(prompt="Say ok.", cwd=tmp_path, allowed_tools="Read")

    carried = flags(_run(request, fake), request.prompt)

    assert "--settings" not in carried
    assert "--disallowedTools" not in carried


def test_a_configured_command_starts_every_run_and_the_login_refresh() -> None:
    """`runtimes.claude_code.command` is the agent the adapter spawns — the
    same binary `abk doctor` looks for — not decoration beside a hard-coded
    `claude`."""
    config.activate(
        WorkspaceConfig.model_validate(
            {"runtimes": {"claude_code": {"command": ["/opt/agent-wrapper", "--quiet"]}}}
        )
    )
    fake = FakeClaude(stdout="ok")
    refreshes: list[list[str]] = []

    argv = _run(AgentRequest(prompt="Say ok."), fake)
    real_refresh_login(run=lambda argv, **kwargs: refreshes.append(argv))

    assert argv[:3] == ["/opt/agent-wrapper", "--quiet", "-p"]
    assert refreshes[0][:3] == ["/opt/agent-wrapper", "--quiet", "-p"]


def test_the_planner_s_graph_call_carries_only_what_it_carries_today() -> None:
    """No worktree, no tools, no permission mode: the planner answers from
    its prompt in the planning repo, and must not gain auto-accepted edits
    there by going through the adapter."""
    fake = FakeClaude(stdout='{"units": []}')
    request = AgentRequest(prompt="Plan the graph.", permission_mode="allowed_tools_only")

    argv = _run(request, fake)

    assert flags(argv, request.prompt) == {"-p": None, "--output-format": "text"}
    assert fake.calls[0][1] is None


def test_research_carries_the_flags_it_carries_today() -> None:
    """Read-only with web access, by its tool list alone."""
    fake = FakeClaude(stdout="## Formatting\n")
    request = AgentRequest(
        prompt="Research python conventions.",
        allowed_tools=RESEARCH_TOOLS,
        permission_mode="allowed_tools_only",
    )

    argv = _run(request, fake)

    assert flags(argv, request.prompt) == {
        "-p": None,
        "--allowedTools": RESEARCH_TOOLS,
        "--output-format": "text",
    }


def test_a_proposal_carries_the_flags_it_carries_today(tmp_path: Path) -> None:
    """Runs in the planning repo, reads the code repo, and carries the hook
    with no `--specs`, since writing a change there is its whole job.

    One intended tightening: the pipeline's deny list now comes with the
    hook, as it does for every policed run. Today's proposal carries the hook
    alone; its tool list allows no Bash beyond `ls`, so the denies take away
    nothing it could do, and the rule that a policy brings both stays whole.
    """
    planning = tmp_path / "planning"
    code = tmp_path / "checkouts" / "app"
    fake = FakeClaude(stdout="Wrote the change.")
    request = AgentRequest(
        prompt="Propose testing-infrastructure for app.",
        cwd=planning,
        add_dirs=(code,),
        allowed_tools=PROPOSE_TOOLS,
        policy=ToolPolicy(specs_dir=None),
    )

    argv = _run(request, fake)
    carried = flags(argv, request.prompt)

    assert json.loads(carried.pop("--settings") or "") == hook(None)
    assert carried == {
        "-p": None,
        "--add-dir": str(code),
        "--allowedTools": PROPOSE_TOOLS,
        "--disallowedTools": DENIED,
        "--permission-mode": "acceptEdits",
        "--output-format": "text",
    }
    assert fake.calls[0][1] == planning


def test_the_restack_resolver_carries_the_flags_it_carries_today(tmp_path: Path) -> None:
    """It edits the conflicted files because its tool list says so, with no
    permission mode. `--output-format text` is new on this call; it is the
    CLI's default, so nothing the call prints changes."""
    fake = FakeClaude(stdout="Resolved.")
    request = AgentRequest(
        prompt="Resolve the conflicts.",
        cwd=tmp_path,
        allowed_tools=RESOLVER_TOOLS,
        permission_mode="allowed_tools_only",
    )

    argv = _run(request, fake)

    assert flags(argv, request.prompt) == {
        "-p": None,
        "--allowedTools": RESOLVER_TOOLS,
        "--output-format": "text",
    }
    assert fake.calls[0][1] == tmp_path
