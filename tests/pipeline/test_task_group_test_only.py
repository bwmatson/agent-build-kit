"""A task group is test-only when its heading tags it `[e2e-test]`, flagged or not."""

from pathlib import Path

import pytest

from agent_build_kit.pipeline.work_graph import TaskGroup, validate_tasks

OPT_OUT = "Acceptance: none — a fixture about test-only groups\n"


def read(heading: str, tmp_path: Path) -> TaskGroup:
    (tmp_path / "tasks.md").write_text(
        f"# Tasks\n\n{OPT_OUT}\n## {heading}\n\n- [ ] 1.1 Test: it.\n"
    )
    groups, errors = validate_tasks(tmp_path / "tasks.md")
    assert errors == []
    return groups[0]


@pytest.mark.parametrize(
    "heading",
    [
        "1. [app] [e2e-test] [acceptance] Drive it",
        "1. [app] [e2e-test] Drive it",
        "1. [app] [e2e-test] [contract] Drive it",
        "1. [app] [e2e-test] [narrow] Drive it",
    ],
)
def test_an_e2e_group_is_test_only_whatever_its_flag(heading: str, tmp_path: Path) -> None:
    assert read(heading, tmp_path).test_only is True


@pytest.mark.parametrize(
    "heading",
    [
        "1. [app] [unit-test] Cover it",
        "1. [app] [integration-test] Cover it",
    ],
)
def test_a_group_of_only_tests_in_another_tier_is_not_test_only(
    heading: str, tmp_path: Path
) -> None:
    assert read(heading, tmp_path).test_only is False
