"""A build run that changes the planning repo's abk.yaml or abk.local.yaml, by whatever route, is
warned about with the diff and goes on; it never fails the unit (spec: sandbox-default). The fake
agent writes with Python, a program the command policy does not name."""

from __future__ import annotations

import stat
from collections.abc import Callable
from pathlib import Path

import pytest

import agent_build_kit
from agent_build_kit import sandboxes
from agent_build_kit.config import active, models
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.config_guard import warning_lines
from agent_build_kit.pipeline.wiring import build_run
from agent_build_kit.runtimes import AgentRateLimited, AgentRequest, AgentResult
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime, spawn
from tests.conftest import make_installation
from tests.pipeline.test_config_unchanged_when_confined import EDITED, step
from tests.pipeline.test_wiring_sandbox import Recording, install
from tests.runtimes.stand_in import StandInRuntime
from tests.runtimes.test_claude_code_sandbox import no_backend
from tests.time_limit import LOADED_TEST_TIME_LIMIT

ORIGINAL = "repos: {}\n"
MAY_HAVE_WRITTEN = "an agent may have written"


def writes(path: Path, text: str) -> Callable[[AgentRequest], None]:
    def act(request: AgentRequest) -> None:
        path.write_text(text)

    return act


def writes_then_stops(path: Path, text: str) -> Callable[[AgentRequest], None]:
    def act(request: AgentRequest) -> None:
        path.write_text(text)
        raise AgentRateLimited("usage window spent")

    return act


def build(planning: Path, tree: Path, agent: StandInRuntime) -> str:
    return build_run(runtime=agent, planning_repo=planning, allowed_tools="Read")(
        "Implement it.", cwd=tree, model=models().implement
    )


def warned(planning: Path) -> list[str]:
    return warning_lines(Installation(active(), planning).state_dir)


@pytest.fixture
def planning(tmp_path: Path) -> Path:
    root = tmp_path / "planning"
    make_installation(root)
    (root / "abk.yaml").write_text(ORIGINAL)
    (root / "abk.local.yaml").write_text("runtime: acp\n")
    return root


@pytest.mark.parametrize("name", ["abk.yaml", "abk.local.yaml"])
def test_an_unconfined_build_run_that_rewrites_a_configuration_file_warns_and_goes_on(
    tmp_path: Path, planning: Path, name: str, capsys: pytest.CaptureFixture[str]
) -> None:
    agent = StandInRuntime(answer="built it", act=writes(planning / name, "review: {enabled: 1}\n"))

    assert build(planning, tmp_path / "tree", agent) == "built it"

    out = capsys.readouterr().out
    assert f"{name} changed during the run" in out
    assert "+review: {enabled: 1}" in out
    assert {"abk.yaml": "-repos: {}", "abk.local.yaml": "-runtime: acp"}[name] in out
    assert MAY_HAVE_WRITTEN in out


def test_an_unconfined_build_run_that_deletes_or_creates_a_file_reports_it_and_goes_on(
    tmp_path: Path, planning: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (planning / "abk.local.yaml").unlink()
    agent = StandInRuntime(answer="built it", act=writes(planning / "abk.local.yaml", "x: 1\n"))

    assert build(planning, tmp_path / "tree", agent) == "built it"

    out = capsys.readouterr().out
    assert "abk.local.yaml changed during the run (was created)" in out


def test_an_unconfined_build_run_that_deletes_a_file_reports_it_and_goes_on(
    tmp_path: Path, planning: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def delete(request: AgentRequest) -> None:
        (planning / "abk.local.yaml").unlink()

    agent = StandInRuntime(answer="built it", act=delete)

    assert build(planning, tmp_path / "tree", agent) == "built it"

    out = capsys.readouterr().out
    assert "abk.local.yaml changed during the run (was deleted)" in out


def test_a_person_editing_during_an_unconfined_run_is_a_warning_and_not_a_failure(
    tmp_path: Path, planning: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    note = ORIGINAL + "# a note\n"
    agent = StandInRuntime(answer="built it", act=writes(planning / "abk.yaml", note))

    assert build(planning, tmp_path / "tree", agent) == "built it"

    out = capsys.readouterr().out
    assert "changed during the run" in out
    assert "requeue" not in out


def test_a_run_leaves_the_changed_file_as_it_is(tmp_path: Path, planning: Path) -> None:
    agent = StandInRuntime(answer="built it", act=writes(planning / "abk.yaml", "changed: 1\n"))

    build(planning, tmp_path / "tree", agent)

    assert (planning / "abk.yaml").read_text() == "changed: 1\n", "it is not restored"


def test_a_build_run_that_rewrites_a_file_and_then_stops_raises_its_own_error_after_the_warning(
    tmp_path: Path, planning: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    agent = StandInRuntime(act=writes_then_stops(planning / "abk.yaml", "review: {enabled: 1}\n"))

    with pytest.raises(AgentRateLimited, match="usage window spent"):
        build(planning, tmp_path / "tree", agent)

    out = capsys.readouterr().out
    assert "abk.yaml changed during the run" in out
    assert "+review: {enabled: 1}" in out


def test_the_warning_is_kept_for_status_until_a_step_that_sees_no_change_clears_it(
    tmp_path: Path, planning: Path
) -> None:
    edit = StandInRuntime(answer="built it", act=writes(planning / "abk.yaml", "changed: 1\n"))
    quiet = StandInRuntime(answer="built it")

    build(planning, tmp_path / "tree", edit)

    assert any("abk.yaml changed during the run" in line for line in warned(planning))

    build(planning, tmp_path / "tree", quiet)

    assert warned(planning) == []


class Spawning(Recording):
    """The real Claude Code runtime, started through the real launcher."""

    def run(self, request: AgentRequest) -> AgentResult:
        return ClaudeCodeRuntime(execute=spawn).run(request)


def test_a_step_that_ran_unconfined_under_required_none_warns_and_the_unit_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    program = tmp_path / "agent-stand-in"
    target = tmp_path / "plan" / "abk.local.yaml"
    program.write_text(
        f"#!/bin/sh\ncat > /dev/null\nprintf '%s' '{EDITED}' > {target}\necho done\n"
    )
    program.chmod(program.stat().st_mode | stat.S_IXUSR)
    root, main = install(tmp_path, enabled=True, required="none", command=[str(program)])
    (root / "abk.local.yaml").write_text("runtime: claude_code\n")
    monkeypatch.setattr(sandboxes, "probe", no_backend)
    lines: list[str] = []

    step(root, main, Spawning(), lines)

    logged = "\n".join(lines)
    assert "abk.local.yaml changed during the run" in logged
    assert MAY_HAVE_WRITTEN in logged


@pytest.mark.time_limit(LOADED_TEST_TIME_LIMIT)
def test_there_is_no_config_changed_in_the_package() -> None:
    package = Path(agent_build_kit.__file__).parent
    named = [
        str(path.relative_to(package))
        for path in package.rglob("*.py")
        if "ConfigChanged" in path.read_text()
    ]

    assert named == []
