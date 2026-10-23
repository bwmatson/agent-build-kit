"""When the step was confined (`process` or `files`), a difference in `abk.yaml` or
`abk.local.yaml` afterwards is logged with its diff and does not fail the unit, and `abk status`
shows it (spec: sandbox-claude-code). A step that was not confined still fails with
`ConfigChanged`: `test_config_unchanged_by_run.py` covers that.
"""

from __future__ import annotations

import argparse
import re
from collections.abc import Callable
from pathlib import Path

import pytest

from agent_build_kit import skills
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.config import models
from agent_build_kit.installation import load_installation
from agent_build_kit.pipeline.wiring import build_run
from agent_build_kit.runtimes import AgentRequest, AgentResult
from agent_build_kit.sandboxes import Coverage
from tests.pipeline.test_wiring_sandbox import Recording, install

DOCS = Path(__file__).resolve().parents[2] / "docs"


class Editing(Recording):
    """A step during which a person edits `abk.local.yaml`."""

    def __init__(self, target: Path, coverage: Coverage) -> None:
        super().__init__()
        self.target = target
        self.sandbox_coverage = coverage

    def run(self, request: AgentRequest) -> AgentResult:
        self.target.write_text("runtime: acp\n")
        return super().run(request)


def edited_step(root: Path, main: Path, coverage: Coverage, lines: list[str]) -> str:
    runtime = Editing(root / "abk.local.yaml", coverage)
    return build_run(runtime=runtime, planning_repo=root, sandbox_repo="app", log=lines.append)(
        "Go.", cwd=main, model=models().implement
    )


@pytest.mark.parametrize("coverage", [Coverage.PROCESS, Coverage.FILES])
def test_a_confined_step_that_sees_the_file_change_logs_the_diff_and_the_unit_continues(
    tmp_path: Path, coverage: Coverage
) -> None:
    root, main = install(tmp_path, enabled=True)
    (root / "abk.local.yaml").write_text("runtime: claude_code\n")
    lines: list[str] = []

    answer = edited_step(root, main, coverage, lines)

    assert answer == "built"
    logged = "\n".join(lines)
    assert "abk.local.yaml changed during the run" in logged
    assert "-runtime: claude_code" in logged
    assert "+runtime: acp" in logged
    assert (root / "abk.local.yaml").read_text() == "runtime: acp\n", "it is not restored"


def test_abk_status_shows_the_warning_of_a_confined_step(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, main = install(tmp_path, enabled=True)
    (root / "abk.local.yaml").write_text("runtime: claude_code\n")
    edited_step(root, main, Coverage.PROCESS, [])
    capsys.readouterr()

    cli.cmd_status(argparse.Namespace(), load_installation(root / "abk.yaml"))

    shown = capsys.readouterr()
    assert "abk.local.yaml changed during the run" in shown.out + shown.err


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
