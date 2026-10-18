"""What the drift test checks of the live-stack tests: every test that starts an agent carries
exactly one runtime tag, and an `acp` scenario with no `claude_code` sibling has a stated reason
in its module's table of reasons (`ACP_ONLY_REASONS`, scenario name to reason; absent is empty)."""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import pytest

from tests.runtime_scratch import AGENT_COMMAND
from tests.runtime_tag_collection import ROOT
from tests.runtime_tags import runtime_tags

REASONS_TABLE = "ACP_ONLY_REASONS"
INTEGRATION = ROOT / "tests" / "integration"
# A module that imports one of these, or reads the agent command setting, starts an agent.
AGENT_HELPERS = ("tests.runtime_scratch", "tests.agent_home")
ACP, CLAUDE_CODE = "runtime_acp", "runtime_claude_code"


def live_modules() -> list[Path]:
    """The live-stack modules of the kit: every module under `tests/integration` marked
    `local_stack`, those that start no agent among them."""
    return sorted(
        path
        for path in INTEGRATION.glob("test_*.py")
        if re.search(r"\blocal_stack\b", path.read_text())
    )


def module_of(item: pytest.Item) -> Any:
    parent = item.getparent(pytest.Module)
    assert parent is not None
    return parent.obj


def starts_an_agent(module: Any) -> bool:
    source = Path(module.__file__).read_text()
    return AGENT_COMMAND in source or any(helper in source for helper in AGENT_HELPERS)


def drift(items: list[pytest.Item]) -> list[str]:
    """One message per offence among the collected `items`, each naming the test or the scenario."""
    found: list[str] = []
    scenarios: dict[tuple[Path, str], set[str]] = defaultdict(set)
    tables: dict[Path, dict[str, str]] = {}
    for item in items:
        tags = runtime_tags(item)
        module = module_of(item)
        path = Path(module.__file__)
        tables[path] = getattr(module, REASONS_TABLE, {})
        scenarios[path, getattr(item, "originalname", item.name)].update(tags)
        if len(tags) > 1:
            found.append(f"{item.nodeid}: carries {len(tags)} runtime tags: {', '.join(tags)}")
        elif not tags and starts_an_agent(module):
            found.append(f"{item.nodeid}: starts an agent and carries no runtime tag")
    for (path, scenario), tags in scenarios.items():
        if ACP in tags and CLAUDE_CODE not in tags and scenario not in tables[path]:
            found.append(
                f"{path.name}::{scenario}: an ACP scenario with no claude_code variant "
                f"and no entry in {REASONS_TABLE}"
            )
    for path, table in tables.items():
        found += [
            f"{path.name}::{scenario}: its entry in {REASONS_TABLE} has an empty reason"
            for scenario, reason in table.items()
            if not reason.strip()
        ]
    return found
