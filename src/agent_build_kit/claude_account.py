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
from agent_build_kit.config import (
    CLAUDE_CODE,
    ClaudeLimitsConfig,
    ConfigError,
    WorkspaceConfig,
    runtime_entry,
)
from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
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


def _directory(account: Account | None) -> Path | None:
    """The directory of `account`, else the one the setting names; None for the default account."""
    if account is not None and account.config_dir is not None:
        return account.config_dir
    return _configured()


def home(account: Account | None = None) -> Path:
    return _directory(account) or _default()


def is_default(account: Account | None = None) -> bool:
    return _directory(account) is None


def environment_entry(account: Account | None = None) -> dict[str, str]:
    """What a `claude` is started with to run in the account: its directory under Claude Code's
    own variable, or nothing for the default account."""
    configured = _directory(account)
    return {VARIABLE: str(configured)} if configured else {}


def credentials_path(account: Account | None = None) -> Path:
    return home(account) / ".credentials.json"


def state_file(account: Account | None = None) -> Path:
    configured = _directory(account)
    return configured / ".claude.json" if configured else Path.home() / ".claude.json"


def skills_dir(account: Account | None = None) -> Path:
    return home(account) / "skills"


def account_key(account: Account | None = None) -> str | None:
    configured = _directory(account)
    return str(configured) if configured else None


class Account(Frozen):
    """A resolved account: the default one (no label, no directory) or a labelled one."""

    label: str | None = None
    config_dir: Path | None = None
    limits: ClaudeLimitsConfig = ClaudeLimitsConfig()
    max_units_in_progress: int | None = None


def file_for(path: Path, account: Account | None) -> Path:
    """`path` for `account`: a labelled account keeps its own file beside it, as
    `name.<label>.ext`, so accounts never share a reading, a cool-down, a call record or an
    allowance. The default account (and none) keeps `path` itself."""
    if account is None or account.label is None:
        return path
    return path.with_name(f"{path.stem}.{account.label}{path.suffix}")


def resolve(inst: Installation, label: str | None) -> Account:
    """The account a repo's `account` label names on this machine: the labelled one when it has
    a `config_dir`, else the default account."""
    return resolve_in(inst.config, label)


def for_repo(config: WorkspaceConfig, repo_name: str) -> Account:
    """The account the units and tracks of the repo `repo_name` run on: its label's account, else
    the default account (also for a name no repo has)."""
    repo = config.repos.get(repo_name)
    return resolve_in(config, repo.account if repo else None)


def resolve_in(config: WorkspaceConfig, label: str | None) -> Account:
    """`resolve` over a loaded configuration, for a caller that holds no `Installation`."""
    entry = runtime_entry(config, name=CLAUDE_CODE)
    named = entry.accounts.get(label) if label is not None else None
    if named is None or named.config_dir is None:
        return Account(limits=entry.limits)
    return Account(
        label=label,
        config_dir=named.config_dir,
        limits=named.limits,
        max_units_in_progress=named.max_units_in_progress,
    )


def slots_per_account(config: WorkspaceConfig) -> bool:
    """Whether units in progress are counted per account: the installation names an account or a
    repo's label. With neither, they are counted per project, as before."""
    entry = runtime_entry(config, name=CLAUDE_CODE)
    return bool(entry.accounts) or any(repo.account for repo in config.repos.values())


def label_of(key: str | None, config: WorkspaceConfig) -> str:
    """How a ledger row's account key reads: the label of the account whose directory it is,
    `default` for the default account (no key, or the directory the environment names), and the
    key itself for a directory nothing names."""
    named = runtime_entry(config, name=CLAUDE_CODE).accounts
    for label, entry in named.items():
        if key is not None and str(entry.config_dir) == key:
            return label
    return "default" if key is None or key == account_key() else key
