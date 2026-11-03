"""`timed_out` says whether a unit-test output holds, as a line of its own, the note that
`run_limited` writes when a command reaches its limit (spec: unit-test-command-limit); the
restack's re-test that times out still raises its error."""

from __future__ import annotations

import sys

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import events
from agent_build_kit.pipeline.command_limit import run_limited, timed_out
from agent_build_kit.pipeline.restack import Moved
from agent_build_kit.pipeline.unit_store import UnitStore
from tests.factories import stored_unit
from tests.pipeline.test_flake_fix_change import change_with_unit, code_repo


def test_the_output_of_a_run_ended_at_its_limit_is_a_timeout() -> None:
    result = run_limited(
        [sys.executable, "-c", "import time; time.sleep(30)"], limit=0.3, grace=0.3
    )

    assert timed_out(result.stdout + result.stderr)


@pytest.mark.parametrize(
    "output",
    [
        "",
        "FAILED tests/test_widget.py::test_a - assert 1 == 2\n",
        "1 failed, 10 passed in 3.2s\n",
        "assert 'unit-test command timed out after 5 seconds and was aborted' in text\n",
    ],
    ids=["empty", "a failed test", "a summary", "a quoted note in a line"],
)
def test_any_other_output_is_not(output: str) -> None:
    assert not timed_out(output)


def test_a_restack_whose_retest_times_out_raises_its_error_as_before(
    installation: Installation,
) -> None:
    code_repo(installation)
    child = change_with_unit(installation, "feature", "feature/1").model_copy(
        update={"pr": 2, "branch": "spec/feature/1", "approved": "approved"}
    )
    store = UnitStore(installation.root / "units.json")
    store.upsert([child])
    restack = events.build_restack(
        repos={"app": installation.checkouts["app"]},
        store=store,
        root=installation.root,
        move=lambda *a, **k: Moved(sha="newsha"),
        unit_test=lambda **kwargs: (
            False,
            "unit-test command timed out after 5400 seconds and was aborted\n",
        ),
        on_flake=None,
        push=lambda *a, **k: "newsha",
        retarget=lambda *a, **k: None,
        comment=lambda *a, **k: None,
        diff_id=lambda repo, base, branch: "same-diff",
        head_of=lambda repo, branch: "approved",
    )

    with pytest.raises(RuntimeError, match="left unpushed"):
        restack(
            branch="spec/feature/1",
            old_base="spec/parent/1",
            new_base="main",
            child=child,
            parent=stored_unit("parent/1", change="parent", pr=1, branch="spec/parent/1"),
        )
