"""The demotion record: a class is demoted by a trigger, further triggers join its record, and
only a lift ends it."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_build_kit.pipeline import demotion_record
from agent_build_kit.pipeline.demotion_record import NotDemoted

ROOT = Path(__file__).resolve().parents[2]
FIRST = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
SECOND = datetime(2026, 1, 2, 9, 0, tzinfo=UTC)
THIRD = datetime(2026, 1, 3, 9, 0, tzinfo=UTC)


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / "runs" / demotion_record.DEMOTIONS


def demote(
    path: Path,
    *,
    trigger: str = "revert",
    unit: str = "c/1",
    at: datetime = FIRST,
    said: list[str] | None = None,
) -> bool:
    messages = said if said is not None else []
    return demotion_record.demote(
        path, unit_class="docs", trigger=trigger, unit=unit, at=at, say=messages.append
    )


def test_demoting_a_class_writes_one_record_with_the_trigger_the_unit_and_the_time(
    path: Path,
) -> None:
    assert demote(path) is True

    records = demotion_record.read_demotions(path)
    assert list(records) == ["docs"]
    text = path.read_text()
    assert "revert" in text
    assert "c/1" in text
    assert FIRST.isoformat() in text
    assert demotion_record.demoted_classes(path) == ("docs",)


def test_a_second_trigger_on_a_demoted_class_joins_its_record_and_is_logged(
    path: Path,
) -> None:
    demote(path)
    said: list[str] = []

    assert demote(path, trigger="audit", unit="c/2", at=SECOND, said=said) is False

    records = demotion_record.read_demotions(path)
    assert list(records) == ["docs"]
    text = path.read_text()
    assert "revert" in text
    assert "audit" in text
    assert "c/2" in text
    assert len(said) == 1
    assert "docs" in said[0]
    assert "audit" in said[0]


def test_the_first_demotion_of_a_class_logs_nothing_of_a_second_trigger(path: Path) -> None:
    said: list[str] = []

    demote(path, said=said)

    assert said == []


def test_lifting_marks_the_demotion_lifted_with_the_time_and_the_class_is_no_longer_demoted(
    path: Path,
) -> None:
    demote(path)

    demotion_record.lift(path, unit_class="docs", at=SECOND)

    assert demotion_record.demoted_classes(path) == ()
    assert SECOND.isoformat() in path.read_text()
    assert "docs" in demotion_record.read_demotions(path)


def test_a_trigger_after_a_lift_makes_a_new_demotion(path: Path) -> None:
    demote(path)
    demotion_record.lift(path, unit_class="docs", at=SECOND)
    said: list[str] = []

    assert demote(path, trigger="verify", unit="c/3", at=THIRD, said=said) is True

    assert demotion_record.demoted_classes(path) == ("docs",)
    assert THIRD.isoformat() in path.read_text()
    assert said == []


def test_lifting_a_class_that_is_not_demoted_is_refused_and_writes_nothing(path: Path) -> None:
    with pytest.raises(NotDemoted):
        demotion_record.lift(path, unit_class="docs", at=SECOND)

    assert not path.exists()


def test_lifting_a_demotion_already_lifted_is_refused(path: Path) -> None:
    demote(path)
    demotion_record.lift(path, unit_class="docs", at=SECOND)

    with pytest.raises(NotDemoted):
        demotion_record.lift(path, unit_class="docs", at=THIRD)


def test_time_passing_does_not_lift_a_demotion(path: Path) -> None:
    demote(path, at=FIRST)

    assert demotion_record.demoted_classes(path) == ("docs",)


def test_there_are_no_demoted_classes_when_there_is_no_file(path: Path) -> None:
    assert demotion_record.read_demotions(path) == {}
    assert demotion_record.demoted_classes(path) == ()


def test_the_policy_file_is_byte_for_byte_unchanged(tmp_path: Path, path: Path) -> None:
    policy = tmp_path / "abk.yaml"
    policy.write_bytes(b"review:\n  auto_land:\n    classes: [docs]\n")
    before = policy.read_bytes()

    demote(path)
    demotion_record.lift(path, unit_class="docs", at=SECOND)

    assert policy.read_bytes() == before
    assert sorted(entry.name for entry in tmp_path.iterdir()) == ["abk.yaml", "runs"]


def test_an_unreadable_file_is_refused_and_left_as_it_is(path: Path) -> None:
    path.parent.mkdir(parents=True)
    path.write_text("not json")

    with pytest.raises(demotion_record.UnreadableDemotions):
        demote(path)
    with pytest.raises(demotion_record.UnreadableDemotions):
        demotion_record.lift(path, unit_class="docs", at=SECOND)

    assert path.read_text() == "not json"


def test_the_file_is_replaced_atomically(path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    demote(path)
    before = path.read_text()

    def interrupt(src: object, dst: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(os, "replace", interrupt)
    with pytest.raises(KeyboardInterrupt):
        demote(path, trigger="audit", unit="c/2", at=SECOND)
    monkeypatch.undo()

    assert path.read_text() == before
    assert [e.name for e in path.parent.iterdir() if e.name.endswith(".tmp")] == []


def test_the_architecture_doc_lists_the_file_with_the_other_state_files() -> None:
    state = (ROOT / "docs" / "architecture.md").read_text().split("## State on disk")[1]
    rows = [line for line in state.splitlines() if line.startswith("| `")]

    assert any(line.startswith(f"| `{demotion_record.DEMOTIONS}`") for line in rows)
