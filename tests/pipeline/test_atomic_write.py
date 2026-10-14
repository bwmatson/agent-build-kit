"""The shared atomic write of a state file (dry-cleanup: one function writes state files)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from agent_build_kit.pipeline.file_lock import atomic_write_text


def names_in(directory: Path) -> list[str]:
    return sorted(entry.name for entry in directory.iterdir())


def test_the_text_lands_in_the_file_and_no_temporary_is_left(tmp_path: Path) -> None:
    path = tmp_path / "state.json"

    atomic_write_text(path, "first\n")

    assert path.read_text() == "first\n"
    assert names_in(tmp_path) == ["state.json"]


def test_an_interrupted_write_keeps_the_previous_content_and_leaves_no_temporary(
    tmp_path: Path,
) -> None:
    path = tmp_path / "state.json"
    path.write_text("old")

    # A lone surrogate cannot be encoded, so the write fails after the temporary is opened.
    with pytest.raises(UnicodeEncodeError):
        atomic_write_text(path, "new \ud800")

    assert path.read_text() == "old"
    assert names_in(tmp_path) == ["state.json"]


def test_an_interrupted_replace_keeps_the_previous_content_and_leaves_no_temporary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "state.json"
    path.write_text("old")

    def interrupt(src: object, dst: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(os, "replace", interrupt)
    with pytest.raises(KeyboardInterrupt):
        atomic_write_text(path, "new")
    monkeypatch.undo()

    assert path.read_text() == "old"
    assert names_in(tmp_path) == ["state.json"]


def test_a_reader_sees_the_old_file_until_the_new_one_is_whole(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "state.json"
    path.write_text("old")
    real = os.replace
    seen: list[tuple[str, str]] = []
    body = "new" * 1000

    def watch(src: str | Path, dst: str | Path) -> None:
        # The moment before the swap: the target is untouched, the temporary is complete.
        seen.append((Path(dst).read_text(), Path(src).read_text()))
        real(src, dst)

    monkeypatch.setattr(os, "replace", watch)
    atomic_write_text(path, body)

    assert seen == [("old", body)]
    assert path.read_text() == body


def test_writers_in_two_processes_do_not_share_a_temporary_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "state.json"
    real = os.replace
    names: list[str] = []

    def spy(src: str | Path, dst: str | Path) -> None:
        names.append(Path(src).name)
        real(src, dst)

    monkeypatch.setattr(os, "replace", spy)
    for pid in (101, 202):
        monkeypatch.setattr(os, "getpid", lambda pid=pid: pid)
        atomic_write_text(path, "from " + str(pid))

    assert len(names) == 2
    assert names[0] != names[1]
