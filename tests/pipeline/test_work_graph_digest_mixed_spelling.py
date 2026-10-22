"""A plan recorded by an earlier release from a tasks file that mixed the old and the new
test-kind spellings still counts as current (spec: tasks-tag-rewrite)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from tests.cli.replan_driver import Replan, tagged_md, tick, ticking_replan
from tests.cli.tags_fix_support import OLD_UNIT_TEST_TAG, run_tags

pytestmark = pytest.mark.usefixtures("scripted_engine")

MIXED = tagged_md(OLD_UNIT_TEST_TAG, "unit-test")


def test_a_plan_recorded_from_a_mixed_text_is_current(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = ticking_replan(tmp_path, monkeypatch, {"feature": MIXED})
    lines = "\n".join(line for line in MIXED.splitlines() if line.strip())
    run.record(
        "feature", sizing=cli.sizing_digest(), hash=hashlib.sha256(lines.encode()).hexdigest()
    )

    assert not cli.has_work(run.inst, run.store)


def recorded_mixed(run: Replan) -> dict:
    lines = "\n".join(line for line in MIXED.splitlines() if line.strip())
    run.record(
        "feature", sizing=cli.sizing_digest(), hash=hashlib.sha256(lines.encode()).hexdigest()
    )
    return run.records["feature"]


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
