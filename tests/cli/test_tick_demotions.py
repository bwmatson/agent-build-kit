"""The demotions in the pipeline pass: evaluated after the outcome sweep when review is enabled,
and an error evaluating one class does not stop the others or fail the pass.

`run_round` is real; the code host is a stand-in and the poll, fetch and usage check are stubbed
at their module boundary, as `test_tick_outcome_sweep` does. A revert is a real commit in the
unit's checkout, so a demotion by revert shows that the sweep ran first."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import demotion_record
from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import UnitState
from agent_build_kit.pipeline.usage_guard import Decision
from agent_build_kit.pipeline.verdict_record import VERDICTS
from tests.conftest import make_installation
from tests.factories import commit, commit_files, init_repo, stored_unit
from tests.forges.stand_in import StandInForge

pytestmark = pytest.mark.usefixtures("scripted_engine")

# Each unit, its pull request and its class.
UNITS = {"change-app-5/1": (5, "docs"), "change-app-5/2": (6, "code")}


@pytest.fixture
def inst(tmp_path: Path) -> Installation:
    return make_installation(
        tmp_path,
        planning={"state_dir": ".", "worktree_root": str(tmp_path.parent / "trees")},
        project_limits={"max_units_in_progress": 50},
        review={"enabled": True},
    )


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "poll_all", lambda inst, **kwargs: None)
    monkeypatch.setattr(cli, "fetch_all", lambda inst: None)
    monkeypatch.setattr(cli, "has_identity", lambda inst, repo: True)
    monkeypatch.setattr(cli, "has_thread", lambda inst, unit_id: False)
    monkeypatch.setattr(cli, "current_usage", lambda: None)
    monkeypatch.setattr(cli, "may_start_unit", lambda r: Decision(may_start=True, reason="plenty"))


@pytest.fixture
def store(inst: Installation, monkeypatch: pytest.MonkeyPatch) -> UnitStore:
    """Two units landed by the pipeline, each merged and then reverted on trunk, with a final
    verdict record each; the outcome is not yet derived."""
    forge = StandInForge()
    monkeypatch.setattr(inst, "forge_of", lambda name: (forge, forge.repo_id()))
    checkout = init_repo(inst.checkouts["app"])
    store = UnitStore(inst.state_dir / "units.json")
    records = {}
    for n, (uid, (pr, unit_class)) in enumerate(UNITS.items()):
        merge = commit(checkout, f"file{n}")
        commit_files(checkout, f"revert\n\nThis reverts commit {merge}.", {f"file{n}": "gone"})
        forge.merged[pr] = merge
        store.upsert([stored_unit(uid, change="change-app-5", repo="app", pr=pr)])
        store.set_state(uid, UnitState.MERGED, pr=pr, branch=f"spec/{uid}", cause=Cause.AUTO_LANDED)
        records[uid] = {
            "brief": True,
            "final": True,
            "unit_class": unit_class,
            "evidence_tier": "auto",
        }
    (inst.state_dir / VERDICTS).write_text(json.dumps(records))
    return store


def run(inst: Installation, store: UnitStore) -> None:
    cli.run_round(inst, store, building=set(), started=set(), only=frozenset(), submit=True)


def demoted(inst: Installation) -> set[str]:
    return set(demotion_record.read_demotions(inst.state_dir / demotion_record.DEMOTIONS))


def test_a_pass_evaluates_the_demotions_after_the_outcome_sweep(
    inst: Installation, store: UnitStore
) -> None:
    run(inst, store)

    assert demoted(inst) == {"docs", "code"}


def test_an_error_evaluating_one_class_is_logged_and_the_others_are_still_evaluated(
    inst: Installation,
    store: UnitStore,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    real = demotion_record.demote

    def demote(path: Path, *, unit_class: str, **kwargs: object) -> bool:
        if unit_class == "docs":
            raise RuntimeError("docs cannot be demoted")
        return real(path, unit_class=unit_class, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(demotion_record, "demote", demote)

    run(inst, store)

    assert demoted(inst) == {"code"}
    assert "docs cannot be demoted" in capsys.readouterr().out
