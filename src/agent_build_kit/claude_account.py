"""The Claude Code account the pipeline runs on: one setting, read as a directory.

The account directory is what Claude Code calls its config directory. It is read
from `CLAUDE_CONFIG_DIR` or `ABK_CLAUDE_HOME` (aliases of one value), from the
process environment or the installation's `.env`, and is never a key of abk.yaml.
The rules are the settings layer's own (`settings.claude_home`); `source` only says
which name and place supplied the value.
"""

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path

from dotenv import dotenv_values
from pydantic import AliasChoices

from agent_build_kit import settings as settings_module
from agent_build_kit.config import ConfigError
from agent_build_kit.settings import Settings, settings

_ALIAS = Settings.model_fields["claude_home"].validation_alias

# The names the setting is read under, in the settings layer's order (`CLAUDE_CONFIG_DIR` first).
NAMES: tuple[str, ...] = (
    tuple(c for c in _ALIAS.choices if isinstance(c, str))
    if isinstance(_ALIAS, AliasChoices)
    else ()
)

# The variable Claude Code reads its account directory from: the first name.
VARIABLE = NAMES[0]


class Source(Enum):
    """Which name, in which place, supplied the account directory."""

    PROCESS_CLAUDE_CONFIG_DIR = "CLAUDE_CONFIG_DIR in the process environment"
    PROCESS_ABK_CLAUDE_HOME = "ABK_CLAUDE_HOME in the process environment"
    ENV_FILE_CLAUDE_CONFIG_DIR = "CLAUDE_CONFIG_DIR in the .env"
    ENV_FILE_ABK_CLAUDE_HOME = "ABK_CLAUDE_HOME in the .env"
    DEFAULT = "the default"


_PROCESS = {
    "CLAUDE_CONFIG_DIR": Source.PROCESS_CLAUDE_CONFIG_DIR,
    "ABK_CLAUDE_HOME": Source.PROCESS_ABK_CLAUDE_HOME,
}
_ENV_FILE = {
    "CLAUDE_CONFIG_DIR": Source.ENV_FILE_CLAUDE_CONFIG_DIR,
    "ABK_CLAUDE_HOME": Source.ENV_FILE_ABK_CLAUDE_HOME,
}


def _supplied(env_file: Path | None) -> tuple[Source, str, str] | None:
    """The source, name and raw value of the first place that sets a name: the process
    before the `.env`, `CLAUDE_CONFIG_DIR` before `ABK_CLAUDE_HOME`; None when none does."""
    for name in NAMES:
        if name in os.environ:
            return _PROCESS[name], name, os.environ[name]
    held = (
        {key.upper(): value for key, value in dotenv_values(env_file).items()} if env_file else {}
    )
    for name in NAMES:
        if name in held:
            return _ENV_FILE[name], name, held[name] or ""
    return None


def source(env_file: Path | None) -> Source:
    found = _supplied(env_file)
    return found[0] if found and found[2] else Source.DEFAULT


def _default() -> Path:
    return Path.home() / ".claude"


def _configured() -> Path | None:
    """The account directory the setting names; None when unset or empty."""
    raw = settings.claude_home
    if raw is None:
        return None
    found = _supplied(settings_module.loaded_env_file)
    if found is not None and not found[2]:
        return None
    path = raw.expanduser()
    if not path.is_absolute():
        where, name = (found[0].value, found[1]) if found else ("the settings", "CLAUDE_CONFIG_DIR")
        raise ConfigError(
            f"{name} is {str(raw)!r} ({where}); write an absolute path, since a relative one "
            "would mean a different directory under each shell and timer"
        )
    return path


def home() -> Path:
    return _configured() or _default()


def is_default() -> bool:
    return _configured() is None


def environment_entry() -> dict[str, str]:
    """What a `claude` is started with to run in the account: its directory under Claude Code's
    own variable, or nothing for the default account."""
    account = _configured()
    return {VARIABLE: str(account)} if account else {}


def credentials_path() -> Path:
    return home() / ".credentials.json"


def state_file() -> Path:
    account = _configured()
    return account / ".claude.json" if account else Path.home() / ".claude.json"


def skills_dir() -> Path:
    return home() / "skills"


def account_key() -> str | None:
    account = _configured()
    return str(account) if account else None
