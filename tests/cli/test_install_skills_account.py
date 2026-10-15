"""`abk install-skills --user` writes to the account's skills directory (spec: claude-account)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import main
from tests.account_settings import Configure

SKILL = Path("abk-pipeline") / "SKILL.md"


def test_user_skills_go_to_the_account_directory_when_set_and_to_the_default_when_not(
    tmp_path: Path, configure: Configure, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    account = tmp_path / "second"
    default = tmp_path / "home" / ".claude" / "skills"
    repo = tmp_path / "app"
    repo.mkdir()

    configure(dotenv={"ABK_CLAUDE_HOME": str(account)})
    assert main(["install-skills", "--user", "--repo", str(repo)]) == 0

    assert (account / "skills" / SKILL).exists()
    assert not default.exists()
    assert (repo / ".claude" / "skills" / SKILL).exists()

    configure()
    assert main(["install-skills", "--user"]) == 0

    assert (default / SKILL).exists()
