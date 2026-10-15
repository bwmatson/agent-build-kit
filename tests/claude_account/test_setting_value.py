"""What the setting's value means: `~` expanded, absolute, empty is unset, and any set value
is an account, even the default directory's own path (spec: claude-account)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import claude_account
from agent_build_kit.config import ConfigError
from tests.account_settings import Configure


def test_a_home_relative_value_is_expanded_whether_or_not_it_exists(
    configure: Configure, tmp_path: Path
) -> None:
    # Written in two parts: the leak check reads a literal home path in text as one.
    configure(dotenv={"CLAUDE_CONFIG_DIR": "~" + "/second"})

    assert claude_account.home() == tmp_path / "home" / "second"
    assert not claude_account.home().exists()


def test_a_relative_value_is_refused_naming_the_value_the_name_and_the_source(
    configure: Configure,
) -> None:
    configure(process={"ABK_CLAUDE_HOME": "accounts/second"})

    with pytest.raises(ConfigError) as refused:
        claude_account.home()

    message = str(refused.value)
    assert "accounts/second" in message
    assert "ABK_CLAUDE_HOME" in message
    assert "process environment" in message
    assert "absolute" in message


def test_a_relative_value_in_the_env_file_names_the_env_file(configure: Configure) -> None:
    configure(dotenv={"CLAUDE_CONFIG_DIR": "second"})

    with pytest.raises(ConfigError) as refused:
        claude_account.home()

    assert "second" in str(refused.value)
    assert "CLAUDE_CONFIG_DIR" in str(refused.value)
    assert ".env" in str(refused.value)


def test_an_empty_process_value_is_the_default_and_the_env_file_is_not_consulted(
    configure: Configure, tmp_path: Path
) -> None:
    env_file = configure(
        process={"CLAUDE_CONFIG_DIR": ""}, dotenv={"ABK_CLAUDE_HOME": "/accounts/a"}
    )

    assert claude_account.home() == tmp_path / "home" / ".claude"
    assert claude_account.is_default()
    assert claude_account.source(env_file) is claude_account.Source.DEFAULT


def test_a_value_equal_to_the_default_directory_is_still_an_account(
    configure: Configure, tmp_path: Path
) -> None:
    default = tmp_path / "home" / ".claude"
    configure(dotenv={"CLAUDE_CONFIG_DIR": str(default)})

    assert claude_account.home() == default
    assert not claude_account.is_default()
