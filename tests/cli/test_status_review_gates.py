"""`abk status` prints a line for each class that clears the gates, with review enabled
(spec: review-outcomes)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import make_installation, run_status
from tests.review_records import sample_records, write_records


def gate_lines(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> list[str]:
    inst = make_installation(
        tmp_path,
        planning=dict(state_dir=".", worktree_root=str(tmp_path.parent / "trees")),
        review=dict(
            classes={"docs": ["docs/**"], "code": ["src/**"]},
            auto_land=dict(min_samples=3, min_clean_rate=0.9),
        ),
    )
    write_records(tmp_path / "verdicts.json", sample_records())
    return [line for line in run_status(inst, monkeypatch, capsys) if "gates" in line.lower()]


def test_a_line_is_printed_for_each_class_that_clears_the_gates_and_for_no_other(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = gate_lines(tmp_path, monkeypatch, capsys)

    # `docs` and the unnamed `app/unit-test` clear; `code` does not.
    assert len(lines) == 2
    assert sum("docs" in line for line in lines) == 1
    assert sum("app/unit-test" in line for line in lines) == 1
    assert all(("nameable" in line) == ("app/unit-test" in line) for line in lines)
