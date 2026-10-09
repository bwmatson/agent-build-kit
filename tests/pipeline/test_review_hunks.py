"""A review note carries its line's diff hunk, and the rework prompt prints it (spec: ui-review).

The patch is a real `git diff`, and the thread anchors are real commits.
"""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.forges import ReviewNote
from agent_build_kit.pipeline.events import note_words, review_lines
from agent_build_kit.pipeline.ui_review import HUNK_CONTEXT, attach_hunks, ui_review_notes
from agent_build_kit.serve.review import ReviewStore, unit_diff
from tests.factories import git, init_repo
from tests.review_repo import commit

UNIT = "feature/2"


def text(**changed: str) -> str:
    return "".join(f"{changed.get(f'n{n}', f'line {n}')}\n" for n in range(1, 41))


def seeded(tmp_path: Path) -> tuple[Path, str]:
    repo = init_repo(tmp_path / "app")
    commit(repo, "a.py", text(), "start")
    git(repo, "checkout", "-q", "-b", "spec/feature/2")
    first = commit(repo, "a.py", text(n2="changed 2", n30="changed 30"), "edit")
    return repo, first


def patch_of(repo: Path) -> str:
    return unit_diff(repo, base="main", branch="spec/feature/2").patch


def note(line: int | None) -> ReviewNote:
    return ReviewNote(id="11", body="rename it", path="a.py", line=line)


def store_in(tmp_path: Path) -> ReviewStore:
    directory = tmp_path / "reviews"
    directory.mkdir()
    return ReviewStore(directory)


def test_a_note_carries_the_hunk_holding_its_line(tmp_path: Path) -> None:
    repo, _ = seeded(tmp_path)

    (found,) = attach_hunks([note(29)], patch_of(repo))

    assert found.hunk.startswith("@@")
    assert "+changed 30" in found.hunk
    assert "changed 2" not in found.hunk
    assert (found.body, found.line) == ("rename it", 29)


def test_a_line_the_diff_does_not_contain_gets_no_hunk(tmp_path: Path) -> None:
    repo, _ = seeded(tmp_path)

    unplaced = attach_hunks([note(15), note(None), note(99)], patch_of(repo))

    assert [n.hunk for n in unplaced] == ["", "", ""]


def test_the_prompt_prints_the_hunk_under_the_comment_line(tmp_path: Path) -> None:
    repo, _ = seeded(tmp_path)
    (found,) = attach_hunks([note(30)], patch_of(repo))

    shown = note_words(found).splitlines()

    assert shown[0] == "[comment 11] a.py:30 — rename it"
    assert shown[1:] == found.hunk.splitlines()
    assert shown[1].startswith("@@")
    assert [line for line in shown[1:] if line.endswith("<- comment")] == [
        "+changed 30  <- comment"
    ]


def test_a_ui_thread_becomes_a_note_at_its_line_with_its_replies(tmp_path: Path) -> None:
    repo, first = seeded(tmp_path)
    store = store_in(tmp_path)
    thread = store.add_thread(
        UNIT, path="a.py", side="new", line=30, start_line=None, commit=first, body="why?"
    )
    store.reply(UNIT, thread.id, "and this?")

    notes = ui_review_notes(store.read(UNIT), repo=repo, tip=first)

    assert [(n.path, n.line, n.live, n.body) for n in notes] == [
        ("a.py", 30, True, "why?"),
        ("a.py", 30, True, "and this?"),
    ]
    assert notes[0].id == thread.id and notes[1].id != thread.id


def test_a_ui_note_whose_line_has_since_changed_is_stale_and_prints_nothing(
    tmp_path: Path,
) -> None:
    repo, first = seeded(tmp_path)
    tip = commit(repo, "a.py", text(n2="changed 2", n30="again 30"), "more")
    store = store_in(tmp_path)
    for line in (2, 30):
        store.add_thread(
            UNIT,
            path="a.py",
            side="new",
            line=line,
            start_line=None,
            commit=first,
            body=f"on {line}",
        )

    notes = ui_review_notes(store.read(UNIT), repo=repo, tip=tip)

    assert {n.body: n.live for n in notes} == {"on 2": True, "on 30": False}
    assert [n.line for n in notes if n.body == "on 2"] == [2]
    assert len(review_lines(notes)) == 1
    assert "on 30" not in "".join(review_lines(notes))


def test_a_note_on_a_deleted_line_marks_that_line_and_no_added_one(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "app")
    commit(repo, "a.py", text(), "start")
    git(repo, "checkout", "-q", "-b", "spec/feature/2")
    # Line 3 is deleted and line 30 rewritten, so old line 3 and new line 3 are different lines.
    tip = commit(repo, "a.py", text(n3="", n30="changed 30").replace("\n\n", "\n", 1), "edit")
    store = store_in(tmp_path)
    store.add_thread(
        UNIT, path="a.py", side="old", line=3, start_line=None, commit=tip, body="keep it"
    )

    (note,) = ui_review_notes(store.read(UNIT), repo=repo, tip=tip)
    (found,) = attach_hunks([note], patch_of(repo))

    marked = [line for line in found.hunk.splitlines() if line.endswith("<- comment")]
    assert note.side == "old" and note.live
    assert marked == ["-line 3  <- comment"]


def test_a_resolved_thread_is_not_live_and_prints_nothing(tmp_path: Path) -> None:
    repo, first = seeded(tmp_path)
    store = store_in(tmp_path)
    thread = store.add_thread(
        UNIT, path="a.py", side="new", line=30, start_line=None, commit=first, body="why?"
    )
    store.reply(UNIT, thread.id, "and this?")
    store.resolve(UNIT, thread.id, True)

    notes = ui_review_notes(store.read(UNIT), repo=repo, tip=first)

    assert [n.live for n in notes] == [False, False]
    assert review_lines(notes) == []


def test_a_hunk_is_printed_once_for_a_thread_and_its_reply(tmp_path: Path) -> None:
    repo, first = seeded(tmp_path)
    store = store_in(tmp_path)
    thread = store.add_thread(
        UNIT, path="a.py", side="new", line=30, start_line=None, commit=first, body="why?"
    )
    store.reply(UNIT, thread.id, "and this?")
    notes = ui_review_notes(store.read(UNIT), repo=repo, tip=first)

    shown = attach_hunks(notes, patch_of(repo))

    assert [bool(n.hunk) for n in shown] == [True, False]


def test_a_hunk_is_a_window_around_the_marked_line(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "app")
    commit(repo, "start.py", "x\n", "start")
    git(repo, "checkout", "-q", "-b", "spec/feature/2")
    commit(repo, "new.py", "".join(f"line {n}\n" for n in range(1, 61)), "add")

    (found,) = attach_hunks([ReviewNote(id="1", body="b", path="new.py", line=30)], patch_of(repo))

    lines = found.hunk.splitlines()
    assert lines[0].startswith("@@")
    assert "+line 30  <- comment" in lines
    assert len(lines) <= 2 * HUNK_CONTEXT + 2


def test_a_resolved_thread_does_not_take_the_hunk_of_an_open_one_on_its_line(
    tmp_path: Path,
) -> None:
    repo, first = seeded(tmp_path)
    store = store_in(tmp_path)
    old = store.add_thread(
        UNIT, path="a.py", side="new", line=30, start_line=None, commit=first, body="old one"
    )
    store.resolve(UNIT, old.id, True)
    store.add_thread(
        UNIT, path="a.py", side="new", line=30, start_line=None, commit=first, body="new one"
    )

    notes = ui_review_notes(store.read(UNIT), repo=repo, tip=first)
    (printed,) = review_lines(attach_hunks(notes, patch_of(repo)))

    assert "new one" in printed
    assert "+changed 30  <- comment" in printed.splitlines()
