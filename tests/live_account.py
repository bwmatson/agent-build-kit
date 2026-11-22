"""How a live test reads the account the environment names, once, for every live test."""

from __future__ import annotations

import os
from pathlib import Path

from agent_build_kit import claude_account


def environment_account(label: str) -> claude_account.Account | None:
    """The account the process environment names, or None for the default account. Read it in a
    module-scoped fixture, before the autouse fixture removes the names from each test."""
    for name in claude_account.NAMES:
        if os.environ.get(name):
            return claude_account.Account(
                label=label, config_dir=Path(os.environ[name]).expanduser()
            )
    return None
