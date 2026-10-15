"""Which name and place supplied the account, agreeing with the settings layer for every
combination, and the paths the account's files have (spec: claude-account)."""

from __future__ import annotations

from itertools import product
from pathlib import Path

import pytest

from agent_build_kit import claude_account
from agent_build_kit.claude_account import Source
from agent_build_kit.settings import settings
from tests.account_settings import Configure

# A different value for each name in each place, so the value says where it came from.
PROCESS = {"CLAUDE_CONFIG_DIR": "/p/claude", "ABK_CLAUDE_HOME": "/p/abk"}
DOTENV = {"CLAUDE_CONFIG_DIR": "/e/claude", "ABK_CLAUDE_HOME": "/e/abk"}

# The names a place may hold: neither, either alone, both.
NAME_SETS = [
    (),
    ("CLAUDE_CONFIG_DIR",),
    ("ABK_CLAUDE_HOME",),
    ("CLAUDE_CONFIG_DIR", "ABK_CLAUDE_HOME"),
]


def expected(process: tuple[str, ...], dotenv: tuple[str, ...]) -> tuple[Source, str | None]:
    """The source and value the rules give: the process before the `.env`, `CLAUDE_CONFIG_DIR`
    before `ABK_CLAUDE_HOME`."""
    if "CLAUDE_CONFIG_DIR" in process:
        return Source.PROCESS_CLAUDE_CONFIG_DIR, PROCESS["CLAUDE_CONFIG_DIR"]
    if "ABK_CLAUDE_HOME" in process:
        return Source.PROCESS_ABK_CLAUDE_HOME, PROCESS["ABK_CLAUDE_HOME"]
    if "CLAUDE_CONFIG_DIR" in dotenv:
        return Source.ENV_FILE_CLAUDE_CONFIG_DIR, DOTENV["CLAUDE_CONFIG_DIR"]
    if "ABK_CLAUDE_HOME" in dotenv:
        return Source.ENV_FILE_ABK_CLAUDE_HOME, DOTENV["ABK_CLAUDE_HOME"]
    return Source.DEFAULT, None


@pytest.mark.parametrize(("process", "dotenv"), list(product(NAME_SETS, NAME_SETS)))
def test_the_source_names_the_place_whose_value_the_settings_hold(
    configure: Configure, process: tuple[str, ...], dotenv: tuple[str, ...]
) -> None:
    env_file = configure(
        process={name: PROCESS[name] for name in process},
        dotenv={name: DOTENV[name] for name in dotenv},
    )

    source, value = expected(process, dotenv)

    assert claude_account.source(env_file) is source
    assert settings.claude_home == (Path(value) if value else None)
    assert claude_account.home() == (Path(value) if value else Path.home() / ".claude")


def test_the_source_with_no_env_file_is_the_process_or_the_default(configure: Configure) -> None:
    configure()
    assert claude_account.source(None) is Source.DEFAULT

    configure(process={"ABK_CLAUDE_HOME": "/p/abk"})
    assert claude_account.source(None) is Source.PROCESS_ABK_CLAUDE_HOME


def test_the_account_files_are_in_its_directory(configure: Configure) -> None:
    configure(dotenv={"ABK_CLAUDE_HOME": "/accounts/a"})

    assert claude_account.credentials_path() == Path("/accounts/a/.credentials.json")
    assert claude_account.state_file() == Path("/accounts/a/.claude.json")
    assert claude_account.skills_dir() == Path("/accounts/a/skills")
    assert claude_account.account_key() == "/accounts/a"


def test_the_default_accounts_files_are_in_the_home_directory(
    configure: Configure, tmp_path: Path
) -> None:
    configure()
    home = tmp_path / "home"

    assert claude_account.credentials_path() == home / ".claude" / ".credentials.json"
    assert claude_account.state_file() == home / ".claude.json"
    assert claude_account.skills_dir() == home / ".claude" / "skills"
    assert claude_account.account_key() is None
