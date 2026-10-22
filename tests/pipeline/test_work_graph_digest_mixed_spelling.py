"""A plan recorded by an earlier release from a tasks file that mixed the old and the new
test-kind spellings still counts as current (spec: tasks-tag-rewrite)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from tests.cli.replan_driver import tagged_md, ticking_replan
from tests.cli.tags_fix_support import OLD_UNIT_TEST_TAG

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
