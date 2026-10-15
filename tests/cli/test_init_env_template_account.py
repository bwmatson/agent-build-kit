"""The `.env.example` `abk init` writes shows the account setting, and init asks nothing
about it (spec: claude-account)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit import runtimes
from agent_build_kit.claude_account import NAMES
from agent_build_kit.init.scaffold import draft_config, write_planning_repo
from agent_build_kit.runtimes.base import questions_of
from tests.factories import fake_openspec, recognised_planning
from tests.init.test_scaffold import detection


def test_the_written_template_has_the_commented_setting_and_init_asks_no_account_question(
    tmp_path: Path,
) -> None:
    planning = recognised_planning(tmp_path / "planning")
    config = draft_config({"app": detection("app", tmp_path)}, planning_dir=planning)
    write_planning_repo(planning, config, run_openspec=fake_openspec)

    lines = (planning / ".env.example").read_text().splitlines()

    index = lines.index("#ABK_CLAUDE_HOME=")
    assert "ABK_CLAUDE_HOME" in NAMES
    sentence = " ".join(line.removeprefix("#").strip() for line in lines[:index][-6:])
    assert "CLAUDE_CONFIG_DIR" in sentence and "default" in sentence

    runtime = runtimes.get("claude_code")
    questions = questions_of(runtime)
    assert not [
        q for q in questions if "claude_home" in q.writes_to.lower() or "ABK_CLAUDE" in q.key
    ]
    assert runtime.requires == ()
