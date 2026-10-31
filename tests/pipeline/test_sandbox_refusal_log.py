"""A host the sandbox refuses for a Claude Code step is said once, in the unit's log, naming the
host (spec: claude-steps-can-renew-their-login). A step that asks for it a hundred times leaves
one line; the next step may say it again; an allowed host leaves none."""

from __future__ import annotations

import subprocess
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_build_kit.runtimes import AgentRequest, ToolPolicy, claude_code
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime
from agent_build_kit.sandboxes import Coverage, SandboxPolicy


class Refusing:
    """An `execute` that is told how to report a refused host, and refuses these in turn."""

    def __init__(self, refused: list[tuple[str, int]]) -> None:
        self.refused = refused

    def __call__(self, argv, *, on_refused=None, **_):
        assert on_refused is not None, "a confined step is given the callback"
        for host, port in self.refused:
            on_refused(host, port)
        return subprocess.CompletedProcess(argv, 0, "done\n", "")


def confined(tmp_path: Path, lines: list[str]) -> AgentRequest:
    policy = SandboxPolicy(
        write=(tmp_path,), read=(), hosts=("api.anthropic.com",), required=Coverage.FILES
    )
    return AgentRequest(
        prompt="Go.", cwd=tmp_path, policy=ToolPolicy(sandbox=policy), on_event=lines.append
    )


def said(lines: list[str]) -> list[str]:
    return [line for line in lines if "not on its allowed list" in line]


def test_a_host_asked_for_three_times_is_said_once(tmp_path: Path) -> None:
    lines: list[str] = []
    refused = [("example.test", 443)] * 3 + [("other.test", 443)]

    ClaudeCodeRuntime(execute=Refusing(refused)).run(confined(tmp_path, lines))

    found = said(lines)
    assert len(found) == 2
    assert "example.test" in found[0] and "other.test" in found[1]
    assert all("the step reached for" in line and "sandbox:" in line for line in found)


def test_the_next_step_says_it_again(tmp_path: Path) -> None:
    lines: list[str] = []
    runtime = ClaudeCodeRuntime(execute=Refusing([("example.test", 443)]))

    runtime.run(confined(tmp_path, lines))
    runtime.run(confined(tmp_path, lines))

    assert len(said(lines)) == 2


def test_a_step_that_is_refused_nothing_says_nothing(tmp_path: Path) -> None:
    lines: list[str] = []

    ClaudeCodeRuntime(execute=Refusing([])).run(confined(tmp_path, lines))

    assert said(lines) == []


def test_a_step_with_no_event_callback_still_runs(tmp_path: Path) -> None:
    request = confined(tmp_path, [])
    request = request.model_copy(update={"on_event": None})

    result = ClaudeCodeRuntime(execute=Refusing([("example.test", 443)])).run(request)

    assert result.ok


def test_an_unconfined_step_is_not_given_the_callback(tmp_path: Path) -> None:
    seen: dict[str, object] = {}

    def execute(argv, **kwargs):
        seen.update(kwargs)
        return subprocess.CompletedProcess(argv, 0, "done\n", "")

    ClaudeCodeRuntime(execute=execute).run(AgentRequest(prompt="Go.", cwd=tmp_path))

    assert "on_refused" not in seen


def test_spawn_gives_confinement_the_callback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    got: dict[str, object] = {}

    @contextmanager
    def fake(sandbox, on_refused=None):
        got["on_refused"] = on_refused
        yield SimpleNamespace(wrap=lambda argv: argv, environment={})

    monkeypatch.setattr(claude_code, "confinement", fake)
    monkeypatch.setattr(
        claude_code, "_spawn", lambda *a, **k: subprocess.CompletedProcess([], 0, "", "")
    )
    policy = SandboxPolicy(write=(), read=(), hosts=(), required=Coverage.NONE)
    callback = lambda host, port: None  # noqa: E731

    claude_code.spawn(["claude"], cwd=tmp_path, sandbox=policy, on_refused=callback)

    assert got["on_refused"] is callback
