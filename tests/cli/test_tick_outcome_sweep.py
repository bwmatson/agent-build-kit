"""The outcome sweep in the pipeline pass: it runs once a pass when review is enabled, not when
it is disabled, and an error in it does not fail the pass.

`run_round` is real; the code host is a stand-in, and the poll, fetch and usage check are
stubbed at their module boundary as `test_label_sweep` does."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_build_kit import config
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.forges.base import RepoId
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import UnitState
from agent_build_kit.pipeline.usage_guard import Decision
from agent_build_kit.pipeline.verdict_record import VERDICTS
from tests.conftest import make_installation
from tests.factories import init_repo, stored_unit
from tests.forges.stand_in import StandInForge

pytestmark = pytest.mark.usefixtures("scripted_engine")

UNIT = "change-app-5/1"
PR = 5


class CountingForge(StandInForge):
    """Counts the merge commits asked for: the sweep asks one per merged unit it derives."""

    def __init__(self) -> None:
        super().__init__()
        self.asked: list[int] = []

    def merge_commit(self, repo: RepoId, pr: int) -> str | None:
        self.asked.append(pr)
        return super().merge_commit(repo, pr)


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
def host(inst: Installation, monkeypatch: pytest.MonkeyPatch) -> CountingForge:
    forge = CountingForge()
    monkeypatch.setattr(inst, "forge_of", lambda name: (forge, forge.repo_id()))
    return forge


@pytest.fixture
def store(inst: Installation) -> UnitStore:
    """One unit merged just now, with a verdict record on file and a checkout to search."""
    for checkout in inst.checkouts.values():
        init_repo(checkout)
    store = UnitStore(inst.state_dir / "units.json")
    unit = stored_unit(UNIT, change="change-app-5", repo="app", state=UnitState.MERGED, pr=PR)
    store.upsert([unit])
    store.set_state(UNIT, UnitState.MERGED, pr=PR, branch=f"spec/{UNIT}")
    (inst.state_dir / VERDICTS).write_text(json.dumps({UNIT: {"brief": True, "final": True}}))
    return store


def run(inst: Installation, store: UnitStore) -> None:
    cli.run_round(inst, store, building=set(), started=set(), only=frozenset(), submit=True)


def recorded(inst: Installation) -> dict:
    return json.loads((inst.state_dir / VERDICTS).read_text())


def test_a_pass_with_review_enabled_runs_the_sweep_once(
    inst: Installation, store: UnitStore, host: CountingForge
) -> None:
    run(inst, store)

    assert host.asked == [PR]
    assert recorded(inst)[UNIT]["outcome"] == "clean"


def test_a_pass_with_review_disabled_does_not_run_it(
    inst: Installation, store: UnitStore, host: CountingForge
) -> None:
    config.activate(
        config.active().model_copy(update={"review": config.ReviewConfig(enabled=False)}),
        config.active_root(),
    )

    run(inst, store)

    assert host.asked == []
    assert "outcome" not in recorded(inst)[UNIT]


def test_a_sweep_that_raises_does_not_fail_the_pass(
    inst: Installation,
    store: UnitStore,
    host: CountingForge,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # A directory where the records should be: reading them raises.
    (inst.state_dir / VERDICTS).unlink()
    (inst.state_dir / VERDICTS).mkdir()

    run(inst, store)

    assert "sweeping review outcomes failed" in capsys.readouterr().out
