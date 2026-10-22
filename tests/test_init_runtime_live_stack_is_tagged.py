"""The installed-agent listing test is tagged for the ACP runtime, with its reason."""

from __future__ import annotations

import pytest

from tests.live_tag_drift import INTEGRATION, REASONS_TABLE, module_of
from tests.runtime_tags import runtime_tags

MODULE = INTEGRATION / "test_init_runtime_live_stack.py"
LISTING = "test_listing_against_the_installed_agent_sends_no_prompt"


def test_every_test_of_the_module_carries_runtime_acp_alone(
    pytester: pytest.Pytester,
) -> None:
    items, _ = pytester.inline_genitems(str(MODULE))
    tags = {item.name: runtime_tags(item) for item in items}

    assert tags[LISTING] == ["runtime_acp"]
    assert {name: t for name, t in tags.items() if t != ["runtime_acp"]} == {}
    assert len(tags) > 1


def test_the_module_states_why_the_listing_test_has_no_claude_variant(
    pytester: pytest.Pytester,
) -> None:
    items, _ = pytester.inline_genitems(str(MODULE))

    table = getattr(module_of(items[0]), REASONS_TABLE, {})

    assert table.get(LISTING, "").strip()
