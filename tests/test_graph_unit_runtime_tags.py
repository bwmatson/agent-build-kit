"""The graph live test runs on Claude Code alone and holds no ACP-only step.

The ACP variant of the scenario, and the check that the agent lists the build's session for
the working directory, are added later by the change that adds the ACP variants.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.runtime_tags import runtime_tags

MODULE = Path(__file__).parent / "integration" / "test_graph_unit.py"


def test_every_item_of_the_graph_test_carries_the_claude_code_tag_alone(
    pytester: pytest.Pytester,
) -> None:
    items, _ = pytester.inline_genitems(str(MODULE))

    assert items
    assert [
        (i.nodeid, runtime_tags(i)) for i in items if runtime_tags(i) != ["runtime_claude_code"]
    ] == []
    assert all(i.get_closest_marker("local_stack") is not None for i in items)
    assert all("claude_code" in i.nodeid for i in items)


def test_the_graph_test_calls_no_acp_only_step() -> None:
    source = MODULE.read_text()

    assert "assert_unit_session_listed" not in source
    assert "assert_session_listed" not in source
    assert "runtime_acp" not in source
