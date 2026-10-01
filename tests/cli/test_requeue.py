"""`abk requeue`: give a failed or held unit another go.

Requeueing by editing the store by hand is easy to get subtly wrong, and was:
a failed unit remembers the step it stopped at (`resume_from`), so putting it
back to `planned` and nothing else sends the next attempt straight past the
agent to a check on a branch that has no work on it. The command is the
supported way, and says which of the two things it is doing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import main
from agent_build_kit.config import dump
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_store import UnitStore
from tests.conftest import make_installation
from tests.factories import unit


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> UnitStore:
    inst: Installation = make_installation(tmp_path / "planning")
    (inst.root / "abk.yaml").write_text(dump(inst.config))
    monkeypatch.chdir(inst.root)
    return UnitStore(inst.state_dir / "units.json")


def failed_at_verify(store: UnitStore, uid: str = "add-marker/1") -> None:
    """A unit that built, then failed its tier 1 check: the case that resumes."""
    store.upsert([unit(uid)])
    store.set_state(uid, "failed", branch=f"spec/{uid}", resume_from="verify")
    store.set_feedback(uid, "tier 1 failed: pre-commit was not found")


def test_a_failed_unit_resumes_where_it_stopped(store: UnitStore, capsys) -> None:
    """The right default when the failure was the environment's: the agent's
    work is on the branch and need not be redone."""
    failed_at_verify(store)

    assert main(["requeue", "add-marker/1"]) == 0

    after = store.get("add-marker/1")
    assert after.state == "planned"
    assert after.resume_from == "verify"
    assert "resuming" in capsys.readouterr().out


def test_restart_throws_the_attempt_away(store: UnitStore, capsys) -> None:
    """For a failure that was the attempt's own — built on the wrong base,
    say — where resuming would judge work that was never valid."""
    failed_at_verify(store)

    assert main(["requeue", "add-marker/1", "--restart"]) == 0

    after = store.get("add-marker/1")
    assert after.state == "planned"
    assert after.resume_from == "", "the next attempt starts at the agent, not past it"
    assert after.feedback == "", "and is not handed a failure that no longer applies"
    assert "starting over" in capsys.readouterr().out


def test_the_reason_is_recorded_in_the_unit_s_history(store: UnitStore) -> None:
    failed_at_verify(store)

    main(["requeue", "add-marker/1", "--restart"])

    assert "requeued" in store.get("add-marker/1").history[-1]["note"]


def test_a_held_unit_can_be_requeued_too(store: UnitStore) -> None:
    store.upsert([unit("add-marker/1")])
    store.set_state("add-marker/1", "held")

    assert main(["requeue", "add-marker/1"]) == 0

    assert store.get("add-marker/1").state == "planned"


@pytest.mark.parametrize("state", ["planned", "running", "in_review", "merged", "closed"])
def test_a_unit_that_is_not_stuck_is_left_alone(store: UnitStore, state: str, capsys) -> None:
    """Requeueing a running unit double-builds it; an in-review one has a PR
    that would be orphaned; a merged one is done."""
    store.upsert([unit("add-marker/1")])
    store.set_state("add-marker/1", state)

    code = main(["requeue", "add-marker/1"])

    assert code == 1
    assert store.get("add-marker/1").state == state
    assert state in capsys.readouterr().out


def test_an_unknown_unit_says_so_and_lists_the_known_ones(store: UnitStore, capsys) -> None:
    store.upsert([unit("add-marker/1")])

    code = main(["requeue", "nope/9"])

    out = capsys.readouterr()
    assert code == 2
    assert "nope/9" in out.err and "add-marker/1" in out.err


# --- --rework ------------------------------------------------------------------
#
# A unit that failed tier 1 on real errors (a type check, a lint rule, a test)
# saved the output, but resuming at `verify` runs the check again and meets the
# same errors with the agent never having seen them. --rework keeps the work and
# hands the agent what failed.


def test_rework_hands_the_agent_the_saved_failure(store: UnitStore, capsys) -> None:
    failed_at_verify(store)
    store.set_feedback("add-marker/1", "tier 1 failed:\nERROR implicit-any in test_x.py")

    assert main(["requeue", "add-marker/1", "--rework"]) == 0

    after = store.get("add-marker/1")
    assert after.state == "planned"
    assert after.resume_from == "", "not past the agent, to a check that fails the same way"
    assert after.feedback == "tier 1 failed:\nERROR implicit-any in test_x.py", "and it keeps it"
    assert after.branch == "spec/add-marker/1", "the work stays"
    assert "rework it from the failure it saved" in capsys.readouterr().out


def test_rework_with_nothing_saved_changes_nothing(store: UnitStore, capsys) -> None:
    """There is nothing to hand the agent, and guessing would redo the build."""
    store.upsert([unit("add-marker/1")])
    store.set_state("add-marker/1", "failed", resume_from="verify")

    assert main(["requeue", "add-marker/1", "--rework"]) == 1

    after = store.get("add-marker/1")
    assert after.state == "failed" and after.resume_from == "verify"
    assert "no saved failure" in capsys.readouterr().out


def test_rework_and_restart_are_exclusive(store: UnitStore) -> None:
    failed_at_verify(store)

    with pytest.raises(SystemExit) as raised:
        main(["requeue", "add-marker/1", "--rework", "--restart"])

    assert raised.value.code == 2
    assert store.get("add-marker/1").state == "failed"


def test_rework_is_recorded_in_the_unit_s_history(store: UnitStore) -> None:
    failed_at_verify(store)

    main(["requeue", "add-marker/1", "--rework"])

    assert "reworking from the saved failure" in str(store.get("add-marker/1").history[-1])


def test_rework_still_refuses_a_unit_that_is_not_failed_or_held(store: UnitStore) -> None:
    store.upsert([unit("add-marker/1")])
    store.set_state("add-marker/1", "in_review", pr=4)

    assert main(["requeue", "add-marker/1", "--rework"]) == 1
    assert store.get("add-marker/1").state == "in_review"
