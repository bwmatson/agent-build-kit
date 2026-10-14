"""The runner `build_runner` assembles asks the real scope decision whether a run executes the
whole marker, and carries the real open-fix gate (spec: tier2-waits-on-open-base-failure-fixes)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.flakes import fix_change_name
from agent_build_kit.pipeline.stack_runner import UnitRunner
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.untouched_failures import PREFIX
from agent_build_kit.pipeline.wiring import build_on_preexisting, build_runner
from tests.conftest import make_installation
from tests.factories import stored_unit
from tests.tier2_scope_fakes import CHANGED, NEW, OLD, branch
from tests.tier2_wait_fakes import OLD as FAILING
from tests.tier2_wait_fakes import verdict_of

TASKS = "# Tasks\n\n## 1. [app] [tier2] Work\n\n- [ ] 1.1 Test: it\n- [ ] 1.2 Make it\n"


def runner_of(
    tmp_path: Path, *, scope: str = "own", dev_stack: bool = False
) -> tuple[UnitRunner, Installation, UnitStore]:
    app: dict[str, Any] = {
        "path": str(tmp_path / "checkouts" / "app"),
        "slug": "example/app",
    }
    if dev_stack:
        app["dev_stack"] = {"script": "scripts/dev-stack.sh"}
    installation = make_installation(
        tmp_path / "planning", repos={"app": app}, limits={"tier2_unit_scope": scope}
    )
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored_unit("add-marker/1", repo="app")])
    tasks = installation.changes_dir / "add-marker" / "tasks.md"
    tasks.parent.mkdir(parents=True)
    tasks.write_text(TASKS)
    built = build_runner(
        stored_unit("add-marker/1", repo="app"),
        store=store,
        installation=installation,
        log=lambda line: None,
    )
    return built, installation, store


def adding_a_test(tmp_path: Path) -> tuple[Path, str]:
    return branch(
        tmp_path,
        {"tests/live/test_new.py": NEW},
        base_files={"tests/live/test_old.py": OLD},
    )


def changing_none(tmp_path: Path) -> tuple[Path, str]:
    return branch(tmp_path, {"README.md": "x\n"}, base_files={"tests/live/test_old.py": OLD})


@pytest.mark.parametrize(
    ("scope", "dev_stack", "adds_a_test", "whole"),
    [
        ("own", False, True, False),
        ("own", False, False, False),
        ("full", False, True, True),
        ("own", True, False, True),
    ],
    ids=["own-with-a-test", "own-with-none", "full", "own-with-a-dev-stack-script"],
)
def test_the_runner_says_whole_exactly_when_the_scope_decision_does(
    tmp_path: Path, scope: str, dev_stack: bool, adds_a_test: bool, whole: bool
) -> None:
    built, _, _ = runner_of(tmp_path, scope=scope, dev_stack=dev_stack)
    repo, base = (adding_a_test if adds_a_test else changing_none)(tmp_path)
    if dev_stack:
        (repo / "scripts").mkdir()
        (repo / "scripts" / "dev-stack.sh").write_text("#!/bin/sh\n")

    assert built.tier2_runs_whole(cwd=repo, base=base) is whole


def test_the_runner_says_whole_when_the_units_tests_cannot_be_listed(tmp_path: Path) -> None:
    built, _, _ = runner_of(tmp_path, scope="own")
    repo, _ = adding_a_test(tmp_path)

    assert built.tier2_runs_whole(cwd=repo, base="no-such-ref") is True
    assert built.tier2_runs_whole(cwd=repo, base=None) is True


def test_the_runners_gate_answers_the_open_fix_of_a_recorded_same_repo_failure(
    tmp_path: Path,
) -> None:
    built, installation, store = runner_of(tmp_path)
    met = stored_unit("feature/1", change="feature", repo="app")
    store.upsert([met])
    verdict = verdict_of(old=(FAILING,))
    build_on_preexisting(store, installation, log=lambda line: None)(
        met, verdict, verdict.pre_existing[0], wait=False
    )

    held = built.on_tier2_gate(stored_unit("add-marker/1", repo="app"))

    assert held == [fix_change_name(FAILING, PREFIX)]


def test_a_changed_test_is_not_a_reason_to_be_whole_under_own(tmp_path: Path) -> None:
    built, _, _ = runner_of(tmp_path, scope="own")
    repo, base = branch(
        tmp_path,
        {"tests/live/test_old.py": CHANGED},
        base_files={"tests/live/test_old.py": OLD},
    )

    assert built.tier2_runs_whole(cwd=repo, base=base) is False
