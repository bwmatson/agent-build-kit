"""A group's `Support:` line: paths in backticks and a reason, read in an `[e2e-test]` group as the
files that group may hold beside tests, docs and the changelog; refused without a reason and
outside an `[e2e-test]` group (spec: e2e-group-scope)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.work_graph import TaskGroup, ValidationError, validate_tasks

SEED = "`scripts/seed-stack.sh`, `compose.e2e.yml`"
FIXTURES = "`tests/fixtures/data/`"


def read(tmp_path: Path, kind: str, *support: str) -> tuple[list[TaskGroup], list[ValidationError]]:
    body = "".join(f"{line}\n" for line in support)
    (tmp_path / "tasks.md").write_text(
        f"# Tasks\n\nAcceptance: none — a fixture\n\n## 1. [app] [{kind}] Group 1\n\n"
        f"{body}\n- [ ] 1.1 Test: it.\n"
    )
    return validate_tasks(
        tmp_path / "tasks.md", repos=("app",), projects={}, splits={"app": ("rest",)}
    )


def line_of(tmp_path: Path, needle: str) -> int:
    lines = (tmp_path / "tasks.md").read_text().splitlines()
    return next(n for n, text in enumerate(lines, start=1) if needle in text)


def test_a_support_line_with_paths_and_a_reason_is_the_groups_support(tmp_path: Path) -> None:
    groups, errors = read(tmp_path, "e2e-test", f"Support: {SEED} — the live tests start the stack")

    assert errors == []
    assert groups[0].support == ("scripts/seed-stack.sh", "compose.e2e.yml")


def test_a_trailing_slash_is_kept_so_it_covers_a_directory(tmp_path: Path) -> None:
    groups, errors = read(tmp_path, "e2e-test", f"Support: {FIXTURES} — recorded responses")

    assert errors == []
    assert groups[0].support == ("tests/fixtures/data/",)


def test_a_second_support_line_adds_paths(tmp_path: Path) -> None:
    groups, errors = read(
        tmp_path,
        "e2e-test",
        f"Support: {SEED} — the live tests start the stack",
        f"Support: {FIXTURES} — recorded responses",
    )

    assert errors == []
    assert groups[0].support == ("scripts/seed-stack.sh", "compose.e2e.yml", "tests/fixtures/data/")


def test_a_support_line_without_a_reason_is_an_error_at_its_line(tmp_path: Path) -> None:
    groups, errors = read(tmp_path, "e2e-test", f"Support: {SEED}")

    assert [e.line for e in errors] == [line_of(tmp_path, "Support:")]
    assert "reason" in errors[0].message
    assert groups[0].support == ()


@pytest.mark.parametrize("kind", ["unit-test", "integration-test"])
def test_a_support_line_outside_an_e2e_group_is_an_error_at_its_line(
    tmp_path: Path, kind: str
) -> None:
    groups, errors = read(tmp_path, kind, f"Support: {SEED} — the tests start the stack")

    assert [e.line for e in errors] == [line_of(tmp_path, "Support:")]
    assert "e2e-test" in errors[0].message
    assert groups[0].support == ()
