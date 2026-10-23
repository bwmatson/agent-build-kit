"""When the step was confined (`process` or `files`), a difference in `abk.yaml` or
`abk.local.yaml` afterwards is logged with its diff and does not fail the unit, and `abk status`
shows it (spec: sandbox-claude-code). A step that was not confined still fails with
`ConfigChanged`: `test_config_unchanged_by_run.py` covers the plain cases, and the one below
covers a step that was given a policy and still ran plain.
"""

from __future__ import annotations

import argparse
import re
import stat
from collections.abc import Callable
from pathlib import Path

import pytest

from agent_build_kit import sandboxes, skills
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.config import models
from agent_build_kit.installation import load_installation
from agent_build_kit.pipeline.config_guard import ConfigChanged
from agent_build_kit.pipeline.wiring import build_run
from agent_build_kit.runtimes import AgentRequest, AgentResult
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime, spawn
from agent_build_kit.sandboxes import Coverage
from tests.pipeline.test_wiring_sandbox import Recording, install
from tests.runtimes.test_claude_code_sandbox import no_backend

# A person's edit that still loads, since `abk status` reads the files afterwards.
EDITED = "project_limits: {max_units_in_progress: 3}\n"
NOTE = "# a person's note\n"
DOCS = Path(__file__).resolve().parents[2] / "docs"


class Editing(Recording):
    """A step during which a person edits `target` into `text` (nothing when `text` is None)."""

    def __init__(
        self, target: Path, text: str | None, coverage: Coverage = Coverage.PROCESS
    ) -> None:
        super().__init__()
        self.target = target
        self.text = text
        self.sandbox_coverage = coverage

    def run(self, request: AgentRequest) -> AgentResult:
        if self.text is not None:
            self.target.write_text(self.text)
        return super().run(request)


def step(root: Path, main: Path, runtime: Recording, lines: list[str]) -> str:
    return build_run(runtime=runtime, planning_repo=root, sandbox_repo="app", log=lines.append)(
        "Go.", cwd=main, model=models().implement
    )


@pytest.mark.parametrize("coverage", [Coverage.PROCESS, Coverage.FILES])
@pytest.mark.parametrize("name", ["abk.yaml", "abk.local.yaml"])
def test_a_confined_step_that_sees_the_file_change_logs_the_diff_and_the_unit_continues(
    tmp_path: Path, coverage: Coverage, name: str
) -> None:
    root, main = install(tmp_path, enabled=True, required=coverage.value)
    (root / "abk.local.yaml").write_text("runtime: claude_code\n")
    target = root / name
    edited = target.read_text() + NOTE
    lines: list[str] = []

    answer = step(root, main, Editing(target, edited, coverage), lines)

    assert answer == "built"
    logged = "\n".join(lines)
    assert f"{name} changed during the run" in logged
    assert f"+{NOTE.strip()}" in logged
    assert target.read_text() == edited, "it is not restored"


def test_abk_status_shows_the_warning_of_a_confined_step_until_a_clean_one_ends(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, main = install(tmp_path, enabled=True)
    (root / "abk.local.yaml").write_text("runtime: claude_code\n")
    step(root, main, Editing(root / "abk.local.yaml", EDITED), [])
    capsys.readouterr()

    cli.cmd_status(argparse.Namespace(), load_installation(root / "abk.yaml"))

    shown = capsys.readouterr()
    assert "abk.local.yaml changed during the run" in shown.out + shown.err

    step(root, main, Editing(root / "abk.local.yaml", None), [])
    capsys.readouterr()

    cli.cmd_status(argparse.Namespace(), load_installation(root / "abk.yaml"))

    shown = capsys.readouterr()
    assert "changed during the run" not in shown.out + shown.err


class Spawning(Recording):
    """The real Claude Code runtime, started through the real launcher."""

    def run(self, request: AgentRequest) -> AgentResult:
        return ClaudeCodeRuntime(execute=spawn).run(request)


def test_a_step_that_ran_unconfined_under_required_none_still_fails_with_config_changed(
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

    with pytest.raises(ConfigChanged, match=r"abk\.local\.yaml changed during the run"):
        step(root, main, Spawning(), [])


def skill_text() -> str:
    return (Path(skills.SKILLS_DIR) / "abk-config" / "SKILL.md").read_text()


@pytest.mark.parametrize(
    "text",
    [
        pytest.param(lambda: (DOCS / "architecture.md").read_text(), id="architecture"),
        pytest.param(lambda: (DOCS / "configuration.md").read_text(), id="configuration"),
        pytest.param(skill_text, id="abk-config skill"),
    ],
)
def test_the_documents_say_a_person_may_edit_the_configuration_during_a_confined_run(
    text: Callable[[], str],
) -> None:
    found = re.search(
        r"confined (?:run|step)[^.]*\b(?:edit|warn)|\b(?:edit|warn)[^.]*confined (?:run|step)",
        text(),
        re.IGNORECASE,
    )

    assert found is not None
