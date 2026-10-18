"""The build live test runs on Claude Code alone and holds no ACP-only step.

The ACP variant of the scenario, the agent's refusal of a forbidden command and the check that
the agent lists the build's session are added later by the change that adds the ACP variants.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.runtime_tag_collection import assert_runs_on_claude_code_alone

MODULE = Path(__file__).parent / "integration" / "test_build_unit.py"


def test_the_build_test_collects_only_claude_code_items_each_with_that_one_tag(
    pytester: pytest.Pytester,
) -> None:
    assert_runs_on_claude_code_alone(pytester, MODULE)


def test_the_build_test_holds_no_acp_only_step() -> None:
    source = MODULE.read_text().lower()

    assert "amend" not in source
    assert "assert_unit_session_listed" not in source
    assert "runtime_acp" not in source
