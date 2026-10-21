"""The build live test runs over every runtime and holds no ACP-only step.

The agent's refusal of a forbidden command and the check that the agent lists the build's session
are added later by the change that adds the ACP-only steps.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.runtime_scratch import RUNTIMES
from tests.runtime_tags import runtime_tags

MODULE = Path(__file__).parent / "integration" / "test_build_unit.py"


def test_the_build_test_collects_an_item_per_runtime_each_with_that_one_tag(
    pytester: pytest.Pytester,
) -> None:
    items, _ = pytester.inline_genitems(str(MODULE))

    assert items
    assert all(i.get_closest_marker("local_stack") is not None for i in items)
    for item in items:
        (tag,) = runtime_tags(item)
        assert item.nodeid.endswith(f"[{tag.removeprefix('runtime_')}]"), item.nodeid
    assert {t.removeprefix("runtime_") for i in items for t in runtime_tags(i)} == set(RUNTIMES)


def test_the_build_test_holds_no_acp_only_step() -> None:
    source = MODULE.read_text().lower()

    assert "amend" not in source
    assert "assert_unit_session_listed" not in source
    assert "runtime_acp" not in source
