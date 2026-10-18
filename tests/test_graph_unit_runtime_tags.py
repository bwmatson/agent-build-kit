"""The graph live test runs on Claude Code alone and holds no ACP-only step.

The ACP variant of the scenario, and the check that the agent lists the build's session for
the working directory, are added later by the change that adds the ACP variants.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.runtime_tag_collection import assert_runs_on_claude_code_alone

MODULE = Path(__file__).parent / "integration" / "test_graph_unit.py"


def test_every_item_of_the_graph_test_carries_the_claude_code_tag_alone(
    pytester: pytest.Pytester,
) -> None:
    assert_runs_on_claude_code_alone(pytester, MODULE)


def test_the_graph_test_calls_no_acp_only_step() -> None:
    source = MODULE.read_text()

    assert "assert_unit_session_listed" not in source
    assert "assert_session_listed" not in source
    assert "runtime_acp" not in source
