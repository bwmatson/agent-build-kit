"""The Claude Code account the pipeline runs on: one setting, read as a directory.

The account directory is what Claude Code calls its config directory. It is read
from `CLAUDE_CONFIG_DIR` or `ABK_CLAUDE_HOME` (aliases of one value), from the
process environment or the installation's `.env`, and is never a key of abk.yaml.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path


class Source(Enum):
    """Which name, in which place, supplied the account directory."""

    PROCESS_CLAUDE_CONFIG_DIR = "CLAUDE_CONFIG_DIR in the process environment"
    PROCESS_ABK_CLAUDE_HOME = "ABK_CLAUDE_HOME in the process environment"
    ENV_FILE_CLAUDE_CONFIG_DIR = "CLAUDE_CONFIG_DIR in the .env"
    ENV_FILE_ABK_CLAUDE_HOME = "ABK_CLAUDE_HOME in the .env"
    DEFAULT = "the default"


def home() -> Path:
    raise NotImplementedError


def is_default() -> bool:
    raise NotImplementedError


def source(env_file: Path | None) -> Source:
    raise NotImplementedError


def credentials_path() -> Path:
    raise NotImplementedError


def state_file() -> Path:
    raise NotImplementedError


def skills_dir() -> Path:
    raise NotImplementedError


def account_key() -> str | None:
    raise NotImplementedError
