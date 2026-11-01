"""The pull-request snapshot has one writer at a time and is replaced whole.

Two repos' pollers share one `prs-<repo>.json` path here, which is how a snapshot holding
more than one repo's section gets written by more than one process.
"""

import json
import os
import threading
from pathlib import Path

import pytest

from agent_build_kit.forges import PullRequest
from agent_build_kit.pipeline.file_lock import try_file_lock
from agent_build_kit.pipeline.pr_poller import Poller

REPOS = ("example/app", "example/platform")


def pull(number: int) -> PullRequest:
    return PullRequest(number=number, head="spec/add-marker/1", base="main", state="open")


def poller(path: Path, repo: str, number: int, gate: threading.Barrier | None = None) -> Poller:
    def list_prs() -> list[PullRequest]:
        if gate is not None:
            gate.wait(timeout=10)
        return [pull(number)]

    return Poller(repo=repo, state_path=path, list_prs=list_prs, dispatch=lambda *a, **k: None)


def test_two_writers_leave_both_repos_sections_with_collected_at(tmp_path: Path) -> None:
    path = tmp_path / "prs-shared.json"
    gate = threading.Barrier(2)
    pollers = [poller(path, repo, 10 + i, gate) for i, repo in enumerate(REPOS)]
    errors: list[BaseException] = []

    def run(one: Poller) -> None:
        try:
            one.poll()
        except BaseException as error:  # noqa: BLE001 - surfaced by the assertion below
            errors.append(error)

    threads = [threading.Thread(target=run, args=(one,)) for one in pollers]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert not errors
    written = json.loads(path.read_text())
    for i, repo in enumerate(REPOS):
        assert "collected_at" in written[repo]
        assert set(written[repo]["prs"]) == {str(10 + i)}


def test_a_second_write_keeps_the_first_repos_section(tmp_path: Path) -> None:
    path = tmp_path / "prs-shared.json"
    for i, repo in enumerate(REPOS):
        poller(path, repo, 10 + i).poll()

    written = json.loads(path.read_text())
    assert set(REPOS) <= set(written)
    for i, repo in enumerate(REPOS):
        assert "collected_at" in written[repo]
        assert set(written[repo]["prs"]) == {str(10 + i)}


def test_the_file_lock_is_held_while_the_snapshot_is_replaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "prs-app.json"
    held: list[bool] = []
    replace = os.replace

    def replace_probing_the_lock(src, dst, *args, **kwargs):
        if Path(dst) == path:
            with try_file_lock(path.with_name(f"{path.name}.lock")) as taken:
                held.append(not taken)
        return replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "replace", replace_probing_the_lock)
    poller(path, REPOS[0], 10).poll()

    assert held == [True]


def test_a_reader_during_a_write_sees_the_old_file_whole(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "prs-app.json"
    one = poller(path, REPOS[0], 10)
    one.poll()
    old = path.read_text()
    json.loads(old)

    seen: list[str] = []
    replace = os.replace

    def replace_after_reading(src, dst, *args, **kwargs):
        if Path(dst) == path:
            seen.append(path.read_text())
        return replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "replace", replace_after_reading)
    one.poll()

    assert seen == [old]
    json.loads(path.read_text())
