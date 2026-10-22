"""`abk tags --fix` refuses a `Needs:` cycle like plain `abk tags`, and `--dry-run` without
`--fix` is a usage error (spec: tasks-tag-rewrite)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.cli.replan_driver import tagged_md
from tests.cli.tags_fix_support import OLD_UNIT_TEST_TAG, planning, run_tags, write_change


def test_dry_run_without_fix_is_a_usage_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = planning(tmp_path, monkeypatch)
    write_change(run, "feature", tagged_md(OLD_UNIT_TEST_TAG).encode())

    code, out = run_tags(capsys, "--dry-run", "feature")

    assert code == 2
    assert "--dry-run needs --fix" in out


def test_a_change_on_a_needs_cycle_is_refused_and_left_as_it_was(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = planning(tmp_path, monkeypatch)
    first = tagged_md(OLD_UNIT_TEST_TAG).replace(
        "\n- [ ] 1.1", "\nNeeds: second group 1 — a reason\n\n- [ ] 1.1", 1
    )
    second = tagged_md(OLD_UNIT_TEST_TAG).replace(
        "\n- [ ] 1.1", "\nNeeds: first group 1 — a reason\n\n- [ ] 1.1", 1
    )
    path = write_change(run, "first", first.encode())
    write_change(run, "second", second.encode())

    code, out = run_tags(capsys, "--fix", "first")

    assert code == 1, out
    assert "refused" in out
    assert path.read_text() == first
