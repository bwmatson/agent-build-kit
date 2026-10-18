"""What the drift test checks of the live-stack tests: every test that starts an agent carries
exactly one runtime tag, and an `acp` scenario with no `claude_code` sibling has a stated reason
in its module's table of reasons (`ACP_ONLY_REASONS`, scenario name to reason; absent is empty)."""

from __future__ import annotations

from pathlib import Path

import pytest

REASONS_TABLE = "ACP_ONLY_REASONS"


def live_modules() -> list[Path]:
    """The live-stack modules of the kit: every module under `tests/integration` marked
    `local_stack`, those that start no agent among them."""
    raise NotImplementedError


def drift(items: list[pytest.Item]) -> list[str]:
    """One message per offence among the collected `items`, each naming the test or the scenario."""
    raise NotImplementedError
