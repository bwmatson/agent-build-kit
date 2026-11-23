"""An intent record names a landing in progress.

It is written before the forge is asked to merge and removed once the merge is
recorded, so a crash between the two leaves a landing the next pass can see: the
poller's merged event for that pull request is recorded as the pipeline's own.
"""

import json
import os
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import events, landing_intent
from agent_build_kit.pipeline.landing_intent import IntentNotWritten
from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import SETTLING
from tests.factories import deep_store

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / landing_intent.LANDING


def merged(store: UnitStore, pr: int, *, landing: Path, repo: str = "app", dispatch: bool = False):
    effects = dict(restack=lambda **k: None, rebase_cap=2, log=lambda m: None)
    if dispatch:
        return events.build_dispatch(store, landing_path=landing, **effects)(
            "merged", pr, repo=repo
        )
    return events.on_merged(pr, repo=repo, store=store, landing_path=landing, **effects)


def test_an_intent_is_there_from_the_write_until_it_is_removed(path: Path) -> None:
    assert not landing_intent.has_intent(path, repo="app", pr=1)

    landing_intent.record_intent(path, repo="app", pr=1, unit="c/1")
    assert landing_intent.has_intent(path, repo="app", pr=1)

    landing_intent.clear_intent(path, repo="app", pr=1)
    assert not landing_intent.has_intent(path, repo="app", pr=1)


def test_the_intent_names_the_unit_and_pull_request(path: Path) -> None:
    landing_intent.record_intent(path, repo="app", pr=7, unit="c/1")

    assert json.loads(path.read_text()) == {
        "app:7": {"repo": "app", "pr": 7, "unit": "c/1"},
    }


def test_an_intent_for_another_pull_request_or_repo_is_ignored(path: Path) -> None:
    landing_intent.record_intent(path, repo="app", pr=1, unit="c/1")

    assert not landing_intent.has_intent(path, repo="app", pr=2)
    assert not landing_intent.has_intent(path, repo="platform", pr=1)


def test_removing_one_intent_leaves_the_others(path: Path) -> None:
    landing_intent.record_intent(path, repo="app", pr=1, unit="c/1")
    landing_intent.record_intent(path, repo="platform", pr=1, unit="d/1")

    landing_intent.clear_intent(path, repo="app", pr=1)

    assert landing_intent.has_intent(path, repo="platform", pr=1)


def test_removing_an_intent_that_is_not_there_changes_nothing(path: Path) -> None:
    landing_intent.clear_intent(path, repo="app", pr=1)

    assert not landing_intent.has_intent(path, repo="app", pr=1)


def test_a_merged_event_for_a_pull_request_with_an_intent_is_recorded_auto_landed(
    tmp_path: Path, path: Path
) -> None:
    store = deep_store(tmp_path)
    landing_intent.record_intent(path, repo="app", pr=1, unit="c/1")

    merged(store, 1, landing=path)

    assert store.get("c/1").state == SETTLING
    assert store.get("c/1").cause == Cause.AUTO_LANDED


def test_the_poller_s_merged_event_reaches_the_intent(tmp_path: Path, path: Path) -> None:
    store = deep_store(tmp_path)
    landing_intent.record_intent(path, repo="app", pr=1, unit="c/1")

    merged(store, 1, landing=path, dispatch=True)

    assert store.get("c/1").cause == Cause.AUTO_LANDED


def test_an_intent_for_another_pull_request_or_repo_leaves_a_merge_a_person_s(
    tmp_path: Path, path: Path
) -> None:
    store = deep_store(tmp_path)
    landing_intent.record_intent(path, repo="app", pr=2, unit="c/2")
    landing_intent.record_intent(path, repo="platform", pr=1, unit="d/1")

    merged(store, 1, landing=path)

    assert store.get("c/1").cause == Cause.MERGED


def test_the_intent_is_removed_once_the_merge_is_recorded(tmp_path: Path, path: Path) -> None:
    store = deep_store(tmp_path)
    landing_intent.record_intent(path, repo="app", pr=1, unit="c/1")
    landing_intent.record_intent(path, repo="app", pr=2, unit="c/2")

    merged(store, 1, landing=path)

    assert store.get("c/1").cause == Cause.AUTO_LANDED
    assert not landing_intent.has_intent(path, repo="app", pr=1)
    assert landing_intent.has_intent(path, repo="app", pr=2)


def test_a_merged_event_for_a_unit_already_recorded_merged_removes_its_intent(
    tmp_path: Path, path: Path
) -> None:
    store = deep_store(tmp_path)
    merged(store, 1, landing=path)
    landing_intent.record_intent(path, repo="app", pr=1, unit="c/1")

    merged(store, 1, landing=path)

    assert not landing_intent.has_intent(path, repo="app", pr=1)
    assert store.get("c/1").cause == Cause.MERGED


def test_the_installation_s_dispatch_reads_the_intent_in_its_state_directory(
    tmp_path: Path, installation: Installation
) -> None:
    store = deep_store(tmp_path)
    state = installation.state_dir / landing_intent.LANDING
    landing_intent.record_intent(state, repo="app", pr=9, unit="c/9")

    cli.deliver_hold_event(installation, store, "merged", store.get("c/9"), say=lambda m: None)

    assert store.get("c/9").cause == Cause.AUTO_LANDED
    assert not landing_intent.has_intent(state, repo="app", pr=9)


def test_an_intent_file_that_cannot_be_read_is_not_written_over(path: Path) -> None:
    path.write_text("{ not json")

    with pytest.raises(IntentNotWritten):
        landing_intent.record_intent(path, repo="app", pr=1, unit="c/1")

    assert path.read_text() == "{ not json"


def test_an_intent_that_cannot_be_written_stops_the_landing_and_says_why(
    tmp_path: Path,
) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("a file where the state directory should be")
    path = blocker / landing_intent.LANDING

    with pytest.raises(IntentNotWritten) as stopped:
        landing_intent.record_intent(path, repo="app", pr=1, unit="c/1")

    assert str(stopped.value), "the reason is there to be recorded"
    assert not landing_intent.has_intent(path, repo="app", pr=1)


def test_the_file_is_replaced_atomically(path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    landing_intent.record_intent(path, repo="app", pr=1, unit="c/1")
    before = path.read_text()

    def interrupt(src: object, dst: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(os, "replace", interrupt)
    with pytest.raises(KeyboardInterrupt):
        landing_intent.record_intent(path, repo="app", pr=2, unit="c/2")
    monkeypatch.undo()

    assert path.read_text() == before
    leftovers = [e.name for e in path.parent.iterdir() if e.name.endswith(".tmp")]
    assert leftovers == []


def test_the_architecture_doc_lists_the_file_with_the_other_state_files() -> None:
    state = (ROOT / "docs" / "architecture.md").read_text().split("## State on disk")[1]
    rows = [line for line in state.splitlines() if line.startswith("| `")]

    assert any(line.startswith(f"| `{landing_intent.LANDING}`") for line in rows)
