"""The account setting's rules are the settings layer's own: aliases of one value,
`CLAUDE_CONFIG_DIR` first within a source, the process before the `.env`, neither set the
default (spec: claude-account)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import claude_account
from tests.account_settings import Configure

A = "/accounts/a"
B = "/accounts/b"


def test_either_name_alone_in_the_env_file_gives_that_directory(configure: Configure) -> None:
    configure(dotenv={"ABK_CLAUDE_HOME": A})
    assert claude_account.home(claude_account.Account.default()) == Path(A)

    configure(dotenv={"CLAUDE_CONFIG_DIR": B})
    assert claude_account.home(claude_account.Account.default()) == Path(B)


@pytest.mark.parametrize(
    "dotenv",
    [
        {"ABK_CLAUDE_HOME": A, "CLAUDE_CONFIG_DIR": B},
        {"CLAUDE_CONFIG_DIR": B, "ABK_CLAUDE_HOME": A},
    ],
    ids=["abk first", "claude first"],
)
def test_both_names_in_the_env_file_give_claude_config_dir_in_either_order(
    configure: Configure, dotenv: dict[str, str]
) -> None:
    configure(dotenv=dotenv)

    assert claude_account.home(claude_account.Account.default()) == Path(B)


def test_both_names_in_the_process_give_claude_config_dir(configure: Configure) -> None:
    configure(process={"ABK_CLAUDE_HOME": A, "CLAUDE_CONFIG_DIR": B})

    assert claude_account.home(claude_account.Account.default()) == Path(B)


def test_a_process_value_beats_the_env_file_whichever_names_each_uses(
    configure: Configure,
) -> None:
    configure(process={"ABK_CLAUDE_HOME": A}, dotenv={"CLAUDE_CONFIG_DIR": B})
    assert claude_account.home(claude_account.Account.default()) == Path(A)

    configure(process={"CLAUDE_CONFIG_DIR": B}, dotenv={"ABK_CLAUDE_HOME": A})
    assert claude_account.home(claude_account.Account.default()) == Path(B)


def test_neither_set_is_the_default_directory(configure: Configure, tmp_path: Path) -> None:
    configure()

    assert claude_account.home(claude_account.Account.default()) == tmp_path / "home" / ".claude"
    assert claude_account.is_default(claude_account.Account.default())


def test_a_set_directory_is_not_the_default(configure: Configure) -> None:
    configure(dotenv={"ABK_CLAUDE_HOME": A})

    assert not claude_account.is_default(claude_account.Account.default())


def test_the_env_file_name_is_matched_whatever_its_case(configure: Configure) -> None:
    env_file = configure(dotenv={"abk_claude_home": A})

    assert claude_account.home(claude_account.Account.default()) == Path(A)
    assert claude_account.source(env_file) is claude_account.Source.ENV_FILE_ABK_CLAUDE_HOME

    env_file = configure(dotenv={"Claude_Config_Dir": B})

    assert claude_account.home(claude_account.Account.default()) == Path(B)
    assert claude_account.source(env_file) is claude_account.Source.ENV_FILE_CLAUDE_CONFIG_DIR
