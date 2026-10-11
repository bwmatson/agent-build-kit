"""The label sweep: a step of every round that takes the stale state label off
the pull requests of units that finished before the pipeline cleared them, a
bounded few a tick, and records each so it is not visited again.

`run_round` is real; the code host is a stand-in per repo, and the poll, fetch
and usage check are stubbed at their module boundary as `test_round` does.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.file_lock import file_lock
from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.units import UnitState
from agent_build_kit.pipeline.usage_guard import Decision
from tests.conftest import make_installation
from tests.factories import stored_unit
from tests.forges.stand_in import StandInForge

pytestmark = pytest.mark.usefixtures("scripted_engine")

SWEPT = "labels-swept.json"
LIMIT = 3


class NoLabelsForge(StandInForge):
    """A host that keeps no labels: every label call is unimplemented."""

    def labels_on(self, *args, **kwargs) -> list[str]:
        raise NotImplementedError

    def add_label(self, *args, **kwargs) -> None:
        raise NotImplementedError

    def set_exclusive_label(self, *args, **kwargs) -> None:
        raise NotImplementedError

    def remove_label(self, *args, **kwargs) -> None:
        raise NotImplementedError


@pytest.fixture
def inst(tmp_path: Path) -> Installation:
    return make_installation(
        tmp_path,
        planning={"state_dir": ".", "worktree_root": str(tmp_path.parent / "trees")},
        limits={"label_sweep_per_tick": LIMIT, "max_units_in_progress": 50},
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
def hosts(inst: Installation, monkeypatch: pytest.MonkeyPatch) -> dict[str, StandInForge]:
    """One stand-in host per repo, reached through the installation as production does."""
    by_repo = {"app": StandInForge(), "platform": StandInForge()}
    monkeypatch.setattr(inst, "forge_of", lambda name: (by_repo[name], by_repo[name].repo_id()))
    return by_repo


@pytest.fixture
def store(inst: Installation) -> UnitStore:
    return UnitStore(inst.state_dir / "units.json")


def finished(number: int, state: str = "merged", *, repo: str = "app") -> StoredUnit:
    change = f"change-{repo}-{number}"
    return stored_unit(f"{change}/1", change=change, repo=repo, state=state, pr=number)


def seed(store: UnitStore, units: list[StoredUnit]) -> None:
    """Store the units in the state and with the pull request each carries: `upsert`
    takes only the plan's shape, so those are recorded as the pipeline records them."""
    store.upsert(units)
    for unit in units:
        store.set_state(unit.id, UnitState(unit.state), pr=unit.pr, branch=f"spec/{unit.id}")


def run(inst: Installation, store: UnitStore) -> list[str]:
    ready = cli.run_round(inst, store, building=set(), started=set(), only=frozenset(), submit=True)
    return [unit.id for unit in ready]


def swept(inst: Installation) -> dict[str, list[int]]:
    path = inst.state_dir / SWEPT
    return json.loads(path.read_text()) if path.exists() else {}


def test_a_merged_units_pull_request_still_in_review_is_cleared_and_recorded(
    inst: Installation, store: UnitStore, hosts: dict[str, StandInForge]
) -> None:
    seed(store, [finished(5)])
    hosts["app"].on_pr[5] = {"in-review", "bug"}

    run(inst, store)

    assert hosts["app"].on_pr[5] == {"bug"}
    assert swept(inst) == {"app": [5]}


def test_a_clean_pull_request_is_recorded_without_a_removal(
    inst: Installation, store: UnitStore, hosts: dict[str, StandInForge]
) -> None:
    seed(store, [finished(5)])
    hosts["app"].on_pr[5] = {"bug"}

    run(inst, store)

    assert hosts["app"].label_removals == []
    assert swept(inst) == {"app": [5]}


def test_a_recorded_pull_request_is_not_visited_again(
    inst: Installation, store: UnitStore, hosts: dict[str, StandInForge]
) -> None:
    seed(store, [finished(5)])
    run(inst, store)
    assert swept(inst) == {"app": [5]}
    hosts["app"].label_reads.clear()
    hosts["app"].on_pr[5] = {"in-review"}

    run(inst, store)

    assert hosts["app"].label_reads == []
    assert hosts["app"].on_pr[5] == {"in-review"}


def test_a_unit_that_is_not_finished_is_never_visited(
    inst: Installation, store: UnitStore, hosts: dict[str, StandInForge]
) -> None:
    seed(
        store, [finished(5, "in_review"), finished(6, "running"), finished(7, "held"), finished(8)]
    )
    for pr in (5, 6, 7, 8):
        hosts["app"].on_pr[pr] = {"in-review"}

    run(inst, store)

    assert hosts["app"].label_reads == [8]
    assert hosts["app"].on_pr[5] == {"in-review"}


@pytest.mark.parametrize("state", ["merged", "closed", "satisfied"])
def test_every_finished_state_is_swept(
    state: str, inst: Installation, store: UnitStore, hosts: dict[str, StandInForge]
) -> None:
    seed(store, [finished(5, state)])
    hosts["app"].on_pr[5] = {"checking"}

    run(inst, store)

    assert hosts["app"].on_pr[5] == set()


def test_a_finished_unit_with_no_pull_request_makes_no_forge_call(
    inst: Installation, store: UnitStore, hosts: dict[str, StandInForge]
) -> None:
    seed(
        store,
        [
            stored_unit("change-none/1", change="change-none", state="closed", pr=None),
            finished(8),
        ],
    )

    run(inst, store)

    assert hosts["app"].label_reads == [8]
    assert swept(inst) == {"app": [8]}


def test_at_most_the_limit_is_handled_a_tick_lowest_number_first_and_the_rest_follow(
    inst: Installation,
    store: UnitStore,
    hosts: dict[str, StandInForge],
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed(store, [finished(number) for number in (9, 4, 7, 2, 8)])
    for number in (9, 4, 7, 2, 8):
        hosts["app"].on_pr[number] = {"in-review"}

    run(inst, store)

    assert swept(inst) == {"app": [2, 4, 7]}
    assert hosts["app"].on_pr[8] == {"in-review"}
    assert "2 remain" in capsys.readouterr().out

    run(inst, store)

    assert sorted(swept(inst)["app"]) == [2, 4, 7, 8, 9]
    assert hosts["app"].on_pr[9] == set()


def test_the_limit_counts_across_repos_lowest_number_first_within_each(
    inst: Installation, store: UnitStore, hosts: dict[str, StandInForge]
) -> None:
    seed(
        store,
        [finished(3, repo="platform"), finished(9), finished(1), finished(2, repo="platform")],
    )
    for host in hosts.values():
        host.on_pr = {number: {"in-review"} for number in (1, 2, 3, 9)}

    run(inst, store)

    handled = {repo: sorted(prs) for repo, prs in swept(inst).items()}
    assert sum(len(prs) for prs in handled.values()) == LIMIT
    for repo, prs in handled.items():
        owned = sorted(unit.pr or 0 for unit in store.all() if unit.repo == repo)
        assert prs == owned[: len(prs)], repo


@pytest.mark.parametrize("failing", ["read", "remove"])
def test_a_failed_clear_is_not_recorded_and_is_tried_again(
    failing: str, inst: Installation, store: UnitStore, hosts: dict[str, StandInForge]
) -> None:
    hosts["app"].label_errors = (failing,)
    seed(store, [finished(5)])
    hosts["app"].on_pr[5] = {"in-review"}

    run(inst, store)

    assert swept(inst).get("app", []) == []
    assert hosts["app"].on_pr[5] == {"in-review"}
    assert store.get("change-app-5/1").state == "merged"

    hosts["app"].label_errors = ()
    run(inst, store)

    assert hosts["app"].on_pr[5] == set()
    assert swept(inst) == {"app": [5]}


def test_a_missing_or_unreadable_record_reads_as_empty_and_costs_one_pass(
    inst: Installation, store: UnitStore, hosts: dict[str, StandInForge]
) -> None:
    seed(store, [finished(5)])
    run(inst, store)
    path = inst.state_dir / SWEPT

    path.unlink()
    hosts["app"].label_reads.clear()
    run(inst, store)

    assert hosts["app"].label_reads == [5]
    assert hosts["app"].label_removals == []
    assert swept(inst) == {"app": [5]}

    path.write_text("{not json")
    run(inst, store)

    assert swept(inst) == {"app": [5]}


def test_the_record_is_replaced_atomically_and_kept_beside_its_lock(
    inst: Installation, store: UnitStore, hosts: dict[str, StandInForge]
) -> None:
    seed(store, [finished(5)])

    run(inst, store)

    names = {path.name for path in inst.state_dir.iterdir()}
    assert {SWEPT, f"{SWEPT}.lock"} <= names
    assert f"{SWEPT}.tmp" not in names

    before = (inst.state_dir / SWEPT).stat().st_ino
    seed(store, [finished(6)])
    run(inst, store)

    assert (inst.state_dir / SWEPT).stat().st_ino != before
    assert swept(inst) == {"app": [5, 6]}


def test_the_record_is_read_under_its_lock(
    inst: Installation, store: UnitStore, hosts: dict[str, StandInForge]
) -> None:
    seed(store, [finished(5)])
    round_ = threading.Thread(target=run, args=(inst, store))

    with file_lock(inst.state_dir / f"{SWEPT}.lock"):
        round_.start()
        round_.join(timeout=0.5)

        assert round_.is_alive()
        assert not (inst.state_dir / SWEPT).exists()
        # Blocked at the read: the host has not been reached yet.
        assert hosts["app"].label_reads == []

    round_.join(timeout=30)
    assert swept(inst) == {"app": [5]}


def test_a_unit_of_a_repo_the_installation_no_longer_lists_is_left_alone(
    inst: Installation,
    store: UnitStore,
    hosts: dict[str, StandInForge],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    asked: list[str] = []

    def forge_of(name: str):
        asked.append(name)
        return hosts[name], hosts[name].repo_id()

    monkeypatch.setattr(inst, "forge_of", forge_of)
    seed(store, [finished(5), finished(6, "closed", repo="removed")])

    run(inst, store)
    run(inst, store)

    out = capsys.readouterr().out
    assert swept(inst) == {"app": [5]}
    assert "removed" not in asked
    assert "failed" not in out.replace("verif", "")
    assert "remain" not in out


def test_the_record_is_written_under_its_lock(
    inst: Installation, store: UnitStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Another process takes the lock after this round has read the record and
    before it writes: the write waits for it."""
    path = inst.state_dir / SWEPT
    seen: dict[str, bool] = {}

    class Racing(StandInForge):
        def labels_on(self, repo, pr):
            held, release = threading.Event(), threading.Event()

            def rival() -> None:
                with file_lock(inst.state_dir / f"{SWEPT}.lock"):
                    held.set()
                    release.wait(timeout=30)

            threading.Thread(target=rival).start()
            assert held.wait(timeout=30)
            threading.Timer(
                0.5, lambda: (seen.update(written=path.exists()), release.set())
            ).start()
            return super().labels_on(repo, pr)

    host = Racing()
    monkeypatch.setattr(inst, "forge_of", lambda name: (host, host.repo_id()))
    seed(store, [finished(5)])

    run(inst, store)

    assert seen == {"written": False}
    assert swept(inst) == {"app": [5]}


def test_repos_are_swept_in_the_installations_order(
    inst: Installation, store: UnitStore, hosts: dict[str, StandInForge]
) -> None:
    seed(store, [finished(1), finished(2), finished(3), finished(9, repo="platform")])

    run(inst, store)

    assert swept(inst) == {"platform": [9], "app": [1, 2]}


def test_a_repo_whose_host_keeps_no_labels_is_recorded_and_visited_no_more(
    inst: Installation, store: UnitStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    bare = NoLabelsForge()
    monkeypatch.setattr(inst, "forge_of", lambda name: (bare, bare.repo_id()))
    seed(store, [finished(5), finished(6, repo="platform")])

    run(inst, store)
    run(inst, store)

    assert {repo: sorted(prs) for repo, prs in swept(inst).items()} == {
        "app": [5],
        "platform": [6],
    }
    assert bare.label_removals == []
    assert bare.label_reads == []


def test_a_failure_in_the_sweep_stops_neither_the_rest_of_the_round_nor_a_build(
    inst: Installation,
    store: UnitStore,
    hosts: dict[str, StandInForge],
    capsys: pytest.CaptureFixture[str],
) -> None:
    # A lock that cannot be taken: the sweep raises where it records.
    (inst.state_dir / f"{SWEPT}.lock").mkdir()
    seed(store, [finished(5), stored_unit("build-me/1", change="build-me", state="planned")])

    ready = run(inst, store)

    out = capsys.readouterr().out
    assert "IsADirectoryError" in out
    assert ready == ["build-me/1"]
