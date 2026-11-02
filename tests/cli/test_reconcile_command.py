"""`abk reconcile [UNIT] [--dry-run] [--accept UNIT]` (spec: pr-reconcile).

The pass reads the poller's cache; `--accept` is the one place that asks the forge directly, so a
person waiting on an answer gets a confirmed one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import main
from agent_build_kit.config import dump
from agent_build_kit.forges import PullRequest
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.pr_poller import PrState, snapshot, state_path
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, MERGED, RUNNING, SETTLING
from agent_build_kit.pipeline.workspaces import branch_lock
from tests.conftest import make_installation
from tests.factories import stored_unit
from tests.forges.stand_in import StandInForge

COMMIT = "9f2c1ab04d" * 4


@pytest.fixture
def inst(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Installation:
    inst = make_installation(tmp_path / "planning")
    (inst.root / "abk.yaml").write_text(dump(inst.config))
    monkeypatch.chdir(inst.root)
    return inst


@pytest.fixture
def store(inst: Installation) -> UnitStore:
    store = UnitStore(inst.state_dir / "units.json")
    store.upsert([stored_unit("feature/1"), stored_unit("feature/2")])
    for number, uid in ((1, "feature/1"), (2, "feature/2")):
        store.set_state(uid, IN_REVIEW, pr=number, branch=f"spec/{uid}")
    return store


def cache(inst: Installation, **states: str) -> None:
    """The poller's snapshot of `app`: pull request number to the state the forge showed."""
    PrState.save(
        state_path(inst.state_dir, "app"),
        {
            number: snapshot(
                PullRequest(
                    number=int(number), head=f"spec/feature/{number}", base="main", state=state
                )
            )
            for number, state in states.items()
        },
        "app",
    )


def forge_showing(
    monkeypatch: pytest.MonkeyPatch, state: str, *, pr: int = 1, commit: str | None = None
) -> StandInForge:
    """A host where pull request `pr` is in `state`; a merged one has produced `commit`."""
    forge = StandInForge(
        prs=[PullRequest(number=pr, head=f"spec/feature/{pr}", base="main", state=state)]
    )
    if state == "merged":
        forge.merged[pr] = commit or COMMIT
    monkeypatch.setattr(
        Installation, "forge_of", lambda self, repo: (forge, forge.repo_id()), raising=True
    )
    return forge


def test_reconcile_corrects_a_merged_unit_and_prints_the_correction(
    inst: Installation,
    store: UnitStore,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forge_showing(monkeypatch, "merged")
    cache(inst, **{"1": "merged", "2": "open"})

    code = main(["reconcile"])

    assert code == 0
    assert store.get("feature/1").state in (SETTLING, MERGED)
    assert store.get("feature/2").state == IN_REVIEW
    out = capsys.readouterr().out
    assert "reconciled: feature/1 #1 merged on the forge" in out
    assert "feature/2" not in out


def test_reconcile_with_a_unit_limits_the_pass_to_it(
    inst: Installation, store: UnitStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    forge_showing(monkeypatch, "merged")
    cache(inst, **{"1": "merged", "2": "merged"})

    code = main(["reconcile", "feature/2"])

    assert code == 0
    assert store.get("feature/2").state in (SETTLING, MERGED)
    assert store.get("feature/1").state == IN_REVIEW


def test_a_second_run_changes_nothing(
    inst: Installation,
    store: UnitStore,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forge_showing(monkeypatch, "merged")
    cache(inst, **{"1": "merged"})
    main(["reconcile"])
    recorded = store.get("feature/1")
    capsys.readouterr()

    code = main(["reconcile"])

    assert code == 0
    assert store.get("feature/1") == recorded
    assert "reconciled:" not in capsys.readouterr().out


def test_dry_run_prints_what_it_would_do_and_writes_nothing(
    inst: Installation,
    store: UnitStore,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forge_showing(monkeypatch, "merged")
    cache(inst, **{"1": "merged"})
    before = store.all()

    code = main(["reconcile", "--dry-run"])

    assert code == 0
    assert store.all() == before
    assert "feature/1" in capsys.readouterr().out


def test_accept_records_a_merge_the_forge_confirms(
    inst: Installation, store: UnitStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    forge_showing(monkeypatch, "merged")

    code = main(["reconcile", "--accept", "feature/1"])

    assert code == 0
    unit = store.get("feature/1")
    assert unit.state in (SETTLING, MERGED)
    assert unit.merge_sha == COMMIT
    (pull,) = unit.pulls
    assert (pull.number, pull.merge_sha) == (1, COMMIT)
    assert pull.merged_at is not None
    assert "abk reconcile" in unit.history[-1]["note"]
    assert store.get("feature/2").state == IN_REVIEW


@pytest.mark.parametrize("shown", ["open", "closed"])
def test_accept_refuses_a_pull_request_the_forge_does_not_show_merged(
    inst: Installation,
    store: UnitStore,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    shown: str,
) -> None:
    forge_showing(monkeypatch, shown)
    before = store.get("feature/1")

    code = main(["reconcile", "--accept", "feature/1"])

    assert code != 0
    assert store.get("feature/1") == before
    assert capsys.readouterr().err, "the refusal says why"


def test_accept_refuses_a_unit_in_settling(
    inst: Installation,
    store: UnitStore,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forge_showing(monkeypatch, "merged")
    store.set_state("feature/1", SETTLING, pr=1, branch="spec/feature/1")
    before = store.get("feature/1")

    code = main(["reconcile", "--accept", "feature/1"])

    assert code != 0
    assert store.get("feature/1") == before
    assert "settling" in capsys.readouterr().err


def test_accept_refuses_a_unit_already_merged(
    inst: Installation,
    store: UnitStore,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forge_showing(monkeypatch, "merged")
    store.set_state("feature/1", MERGED, pr=1, branch="spec/feature/1")
    before = store.get("feature/1")

    code = main(["reconcile", "--accept", "feature/1"])

    assert code == 1
    assert store.get("feature/1") == before
    assert "merged" in capsys.readouterr().err


def test_accept_refuses_a_unit_with_no_pull_request(
    inst: Installation,
    store: UnitStore,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forge_showing(monkeypatch, "merged")
    store.upsert([stored_unit("feature/3")])
    store.set_state("feature/3", RUNNING, branch="spec/feature/3")
    before = store.get("feature/3")

    code = main(["reconcile", "--accept", "feature/3"])

    assert code == 1
    assert store.get("feature/3") == before
    assert "no pull request" in capsys.readouterr().err


def test_accept_while_a_tick_holds_the_units_branch_changes_nothing(
    inst: Installation,
    store: UnitStore,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forge_showing(monkeypatch, "merged")
    before = store.get("feature/1")

    with branch_lock("spec/feature/1", root=inst.locks_dir):
        code = main(["reconcile", "--accept", "feature/1"])

    assert code == 1
    assert store.get("feature/1") == before
    assert "a tick is handling" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv", [["feature/2", "--accept", "feature/1"], ["--dry-run", "--accept", "feature/1"]]
)
def test_accept_with_a_unit_argument_or_dry_run_is_a_usage_error(
    inst: Installation,
    store: UnitStore,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    argv: list[str],
) -> None:
    forge_showing(monkeypatch, "merged")
    before = store.all()

    code = main(["reconcile", *argv])

    assert code == 2
    assert store.all() == before
    assert "--accept" in capsys.readouterr().err


@pytest.mark.parametrize("argv", [["nope/1"], ["--accept", "nope/1"]])
def test_an_unknown_unit_is_refused(
    inst: Installation, store: UnitStore, capsys: pytest.CaptureFixture[str], argv: list[str]
) -> None:
    code = main(["reconcile", *argv])

    assert code == 2
    assert "no unit 'nope/1'" in capsys.readouterr().err
