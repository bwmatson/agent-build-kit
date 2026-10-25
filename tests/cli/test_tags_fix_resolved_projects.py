"""`abk tags --fix` moves a plan record to the hash `plan_digest` gives the rewritten text, the
projects its groups resolve to included, so the plan stays current (spec: project-resolution)."""

from __future__ import annotations

import hashlib

import pytest

from agent_build_kit.cli.pipeline import plan_digest
from agent_build_kit.pipeline.work_graph import specification_text
from tests.cli.replan_driver import Replan
from tests.cli.tags_fix_support import OLD_UNIT_TEST_TAG, run_tags, write_change
from tests.project_workspace import repos_declaring


def test_a_plan_recorded_before_the_rewrite_stays_current_for_a_group_resolved_to_a_project(
    tmp_path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(
        tmp_path, monkeypatch, repos=repos_declaring(tmp_path / "planning", "app", ("web",))
    )
    text = (
        "# Tasks\n\nAcceptance: none — a fixture about tags\n\n"
        f"## 1. [app] [{OLD_UNIT_TEST_TAG}] Add it\n\n"
        "- [ ] 1.1 Test: it.\n- [ ] 1.2 Edit `web/src/app.ts`.\n"
    )
    path = write_change(run, "feature", text.encode())
    written_as_is = specification_text(text, lambda tag: tag, {1: "web"})
    run.record("feature", hash=hashlib.sha256(written_as_is.encode()).hexdigest())

    code, out = run_tags(capsys, "--fix", "feature")

    assert code == 0, out
    assert OLD_UNIT_TEST_TAG not in path.read_text().splitlines()[4]
    assert run.records["feature"]["hash"] == plan_digest(path, inst=run.inst)
