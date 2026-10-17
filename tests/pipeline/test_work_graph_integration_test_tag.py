"""`[integration-test]` is read as the middle test kind; near misses stay refused."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.model import TestTier
from agent_build_kit.pipeline.work_graph import validate_tasks
from tests.cli.replan_driver import tagged_md


def read(tmp_path: Path, text: str):
    (tmp_path / "tasks.md").write_text(text)
    return validate_tasks(tmp_path / "tasks.md")


def test_the_three_tags_are_read_as_the_three_kinds_in_order(tmp_path: Path) -> None:
    groups, errors = read(tmp_path, tagged_md("unit-test", "integration-test", "e2e-test"))

    assert errors == []
    assert [g.tier for g in groups] == [
        TestTier.UNIT_TEST,
        TestTier("integration-test"),
        TestTier.E2E_TEST,
    ]


@pytest.mark.parametrize("tag", ["integration", "tier3"])
def test_a_near_miss_is_refused_naming_all_three_tags(tmp_path: Path, tag: str) -> None:
    groups, errors = read(tmp_path, tagged_md(tag))

    assert groups == []
    (error,) = errors
    for accepted in ("unit-test", "integration-test", "e2e-test"):
        assert accepted in error.message


def test_acceptance_on_an_integration_test_group_is_refused_naming_e2e_test(
    tmp_path: Path,
) -> None:
    text = tagged_md("integration-test").replace(
        "[integration-test]", "[integration-test] [acceptance]"
    )

    _, errors = read(tmp_path, text)

    (error,) = errors
    assert "acceptance" in error.message and "e2e-test" in error.message
    assert "unknown tier" not in error.message
