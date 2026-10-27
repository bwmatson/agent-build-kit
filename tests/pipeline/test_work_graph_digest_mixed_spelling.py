"""A plan recorded by an earlier release from a tasks file that mixed the old and the new
test-kind spellings still counts as current (spec: tasks-tag-rewrite)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline import file_lock as file_lock_module
from tests.cli.replan_driver import Replan, answer, planned, tagged_md, tick, ticking_replan
from tests.cli.tags_fix_support import (
    OLD_UNIT_TEST_TAG,
    recorded_before_the_tag_was_renamed,
    run_tags,
)

pytestmark = pytest.mark.usefixtures("scripted_engine")

MIXED = tagged_md(OLD_UNIT_TEST_TAG, "unit-test")


def test_a_plan_recorded_from_a_mixed_text_is_current(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = ticking_replan(tmp_path, monkeypatch, {"feature": MIXED})
    recorded_mixed(run)

    assert not cli.has_work(run.inst, run.store)


def recorded_mixed(run: Replan, text: str = MIXED) -> dict:
    run.record(
        "feature",
        sizing=cli.sizing_digest(),
        hash=recorded_before_the_tag_was_renamed(text),
    )
    return run.records["feature"]


def test_tags_fix_does_not_adopt_an_edit_made_after_the_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = ticking_replan(tmp_path, monkeypatch, {"feature": MIXED})
    before = recorded_mixed(run)
    run.write("feature", MIXED + "- [ ] 2.3 Another task.\n")
    assert cli.has_work(run.inst, run.store)

    code, out = run_tags(capsys, "--fix", "feature")

    assert code == 0, out
    assert OLD_UNIT_TEST_TAG not in (run.inst.changes_dir / "feature" / "tasks.md").read_text()
    assert run.records["feature"] == before
    assert cli.has_work(run.inst, run.store)
    run.runtime.answer = answer(planned("feature/1", (1,)))
    _, out = tick(run, capsys)
    assert run.calls == 1, out


def test_tags_fix_holds_the_tasks_file_lock_while_it_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = ticking_replan(tmp_path, monkeypatch, {"feature": MIXED})
    held: list[Path] = []
    written_under: list[tuple[Path, ...]] = []
    real_lock, real_write = file_lock_module.file_lock, cli.atomic_write_bytes

    @contextmanager
    def recording_lock(path: Path) -> Iterator[None]:
        held.append(path)
        with real_lock(path):
            yield
        held.remove(path)

    def recording_write(path: Path, data: bytes) -> None:
        written_under.append(tuple(held))
        real_write(path, data)

    monkeypatch.setattr(file_lock_module, "file_lock", recording_lock)
    monkeypatch.setattr(cli, "atomic_write_bytes", recording_write)

    code, out = run_tags(capsys, "--fix", "feature")

    assert code == 0, out
    lock = run.inst.local_dir / "locks" / "changes" / "feature" / "tasks.md.lock"
    assert written_under == [(lock,)]


def test_tags_fix_keeps_a_plan_recorded_from_a_mixed_text_current(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = ticking_replan(tmp_path, monkeypatch, {"feature": MIXED})
    before = recorded_mixed(run)

    code, out = run_tags(capsys, "--fix", "feature")

    assert code == 0, out
    assert OLD_UNIT_TEST_TAG not in (run.inst.changes_dir / "feature" / "tasks.md").read_text()
    assert not cli.has_work(run.inst, run.store)
    after = run.records["feature"]
    assert after | {"hash": before["hash"]} == before, "only the hash moves"
    _, out = tick(run, capsys)
    assert run.calls == 0, out


def test_a_dry_run_leaves_the_plan_record_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = ticking_replan(tmp_path, monkeypatch, {"feature": MIXED})
    before = recorded_mixed(run)
    planned_json = run.inst.state_dir / "planned.json"
    bytes_before = planned_json.read_bytes()

    code, out = run_tags(capsys, "--fix", "--dry-run", "feature")

    assert code == 0, out
    assert planned_json.read_bytes() == bytes_before
    assert run.records["feature"] == before
