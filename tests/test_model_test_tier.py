"""`TestTier` is the one type for a test kind, in the order of its width."""

from __future__ import annotations

from agent_build_kit.model import TestTier
from agent_build_kit.pipeline.work_graph import TEST_KIND_TAGS


def test_the_kinds_are_the_three_members_in_order_of_width() -> None:
    assert [(kind.name, kind.value) for kind in TestTier] == [
        ("UNIT_TEST", "unit-test"),
        ("INTEGRATION_TEST", "integration-test"),
        ("E2E_TEST", "e2e-test"),
    ]


def test_the_tags_list_the_same_three_values() -> None:
    assert TEST_KIND_TAGS == ("unit-test", "integration-test", "e2e-test")
