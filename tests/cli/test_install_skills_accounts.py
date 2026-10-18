"""`abk install-skills --user` installs under each labelled account's directory beside the
default account's (spec: claude-accounts)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import main
from tests.account_settings import Configure
from tests.test_claude_accounts_registry import kit_overlay, planning_files

SKILL = Path("abk-pipeline") / "SKILL.md"


def test_user_skills_install_under_the_labelled_account_and_the_default(
    tmp_path: Path, configure: Configure, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure()
    planning = tmp_path / "plan"
    planning.mkdir()
    kit_home = tmp_path / "kit-home"
    planning_files(planning, local=kit_overlay(kit_home))
    monkeypatch.chdir(planning)

    assert main(["install-skills", "--user"]) == 0

    assert (kit_home / "skills" / SKILL).exists()
    assert (tmp_path / "home" / ".claude" / "skills" / SKILL).exists()
