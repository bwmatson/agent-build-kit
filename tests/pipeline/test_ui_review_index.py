"""The poll reads the unit store once, not once per pull request (spec: pr-poll-speed).

The unit store is real and its reads are counted; the code host is a stand-in.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from agent_build_kit.forges import PullRequest
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.ui_review import ui_listing, ui_notes_of, ui_reply_writer
from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.serve.review import ReviewStore
from tests.conftest import make_installation
from tests.factories import stored_unit
from tests.forges.stand_in import StandInForge

UNITS = 400
PULLS = 500


class ReadSpy:
    """Counts `UnitStore._read` calls, except those made inside `quiet()` (a test's own writes)."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.reads = 0
        self._muted = False
        original = UnitStore._read

        def counted(store: UnitStore):
            if not self._muted:
                self.reads += 1
            return original(store)

        monkeypatch.setattr(UnitStore, "_read", counted)

    @contextmanager
    def quiet(self) -> Iterator[None]:
        self._muted = True
        try:
            yield
        finally:
            self._muted = False


def owned(number: int, *, pr: int | None) -> StoredUnit:
    return stored_unit(f"change-{number}/1", change=f"change-{number}", repo="app", pr=pr)


@pytest.fixture
def inst(tmp_path: Path) -> Installation:
    return make_installation(tmp_path / "planning")


@pytest.fixture
def store(inst: Installation) -> UnitStore:
    units = UnitStore(inst.state_dir / "units.json")
    units.import_units([owned(n, pr=1000 + n) for n in range(UNITS)])
    return units


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> ReadSpy:
    return ReadSpy(monkeypatch)


def listing(
    inst: Installation,
    store: UnitStore,
    monkeypatch: pytest.MonkeyPatch,
    numbers: list[int],
) -> Callable[[], list[PullRequest]]:
    prs = [
        PullRequest(number=number, head=f"spec/change-{number}/1", base="main", state="open")
        for number in numbers
    ]
    forge = StandInForge(prs=prs)
    monkeypatch.setattr(inst, "forge_of", lambda repo: (forge, forge.repo_id()))
    return ui_listing(inst, store, "app")


def test_a_listing_of_many_pull_requests_reads_the_store_at_most_twice(
    inst: Installation, store: UnitStore, spy: ReadSpy, monkeypatch: pytest.MonkeyPatch
) -> None:
    listed = listing(inst, store, monkeypatch, [1000 + n for n in range(PULLS)])()

    assert len(listed) == PULLS
    assert spy.reads <= 2


def test_a_unit_written_between_two_listings_is_found_by_the_second(
    inst: Installation, store: UnitStore, spy: ReadSpy, monkeypatch: pytest.MonkeyPatch
) -> None:
    new_pr = 5000
    poll = listing(inst, store, monkeypatch, [1000 + n for n in range(100)] + [new_pr])
    before = poll()
    with spy.quiet():
        store.import_units([owned(UNITS, pr=new_pr)])
        thread = ReviewStore(inst.state_dir / "reviews").add_thread(
            f"change-{UNITS}/1",
            path="two.py",
            side="new",
            line=3,
            start_line=None,
            commit="abc",
            body="why?",
        )

    after = poll()

    assert thread.id not in before[-1].conversation
    assert thread.id in after[-1].conversation
    assert spy.reads <= 2


def test_pull_requests_with_no_unit_get_no_review_without_a_read_per_pull_request(
    inst: Installation, store: UnitStore, spy: ReadSpy, monkeypatch: pytest.MonkeyPatch
) -> None:
    numbers = [9000 + n for n in range(PULLS)]

    listed = listing(inst, store, monkeypatch, numbers)()

    assert [pull.number for pull in listed] == numbers
    assert all(pull.conversation == () for pull in listed)
    assert spy.reads <= 2


def test_a_store_file_that_does_not_exist_gives_no_review_without_a_read_per_pull_request(
    inst: Installation, spy: ReadSpy, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = UnitStore(inst.state_dir / "absent" / "units.json")
    numbers = [1000 + n for n in range(PULLS)]

    listed = listing(inst, missing, monkeypatch, numbers)()

    assert [pull.number for pull in listed] == numbers
    assert all(pull.conversation == () for pull in listed)
    assert spy.reads <= 2


def test_the_review_notes_for_many_pull_requests_read_the_store_at_most_twice(
    inst: Installation, store: UnitStore, spy: ReadSpy
) -> None:
    notes = ui_notes_of(inst, store)

    answers = [notes("app", 1000 + n) for n in range(100)]

    assert answers == [[]] * 100
    assert spy.reads <= 2


def test_the_reply_writer_for_many_pull_requests_reads_the_store_at_most_twice(
    inst: Installation, store: UnitStore, spy: ReadSpy
) -> None:
    write = ui_reply_writer(inst.state_dir, store)

    answers = [write("app", 1000 + n, []) for n in range(100)]

    assert answers == [[]] * 100
    assert spy.reads <= 2
