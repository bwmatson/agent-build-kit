"""The output cap is idempotent and driven by a step a test calls (spec: flaky-tests).

Cutting a file keeps the limit minus the marker's length of tail, leaves alone a file
that already begins with the marker and is within the limit, and removes the hole an
open writer leaves on the next call. The loop that runs it signals after each pass.
"""

from __future__ import annotations

import os
from pathlib import Path

from agent_build_kit.pipeline.scratch import cap_files, watch_folder

LINE = 11  # len("line 00000\n")
CAP = 2000
LONG_AGO = 1_000_000_000


def lines(start: int, stop: int) -> list[str]:
    return [f"line {number:05d}\n" for number in range(start, stop)]


def marker_of(text: bytes) -> bytes:
    return text.split(b"\n", 1)[0] + b"\n"


def age(path: Path) -> None:
    os.utime(path, (LONG_AGO, LONG_AGO))


def test_a_cut_file_is_a_marker_and_the_tail_and_is_within_the_limit(tmp_path: Path) -> None:
    body = lines(0, 5000)
    (tmp_path / "suite.log").write_text("".join(body))

    cap_files(tmp_path, max_bytes=CAP)

    text = (tmp_path / "suite.log").read_bytes()
    marker = marker_of(text)
    assert b"truncated" in marker
    assert CAP - LINE < len(text) <= CAP, "the marker and its tail fill the limit, not exceed it"
    assert text.endswith(body[-1].encode())
    assert text[len(marker) :].decode().startswith("line ")


def test_a_file_that_begins_with_the_marker_and_is_within_the_limit_is_not_rewritten(
    tmp_path: Path,
) -> None:
    path = tmp_path / "suite.log"
    path.write_text("".join(lines(0, 5000)))
    cap_files(tmp_path, max_bytes=CAP)
    age(path)
    before = path.read_bytes()

    # A larger limit: the file begins with a marker and is within it.
    cap_files(tmp_path, max_bytes=CAP + 1000)

    assert path.read_bytes() == before
    assert path.stat().st_mtime_ns == LONG_AGO * 1_000_000_000


def test_a_second_cut_of_an_idle_file_changes_nothing(tmp_path: Path) -> None:
    path = tmp_path / "suite.log"
    path.write_text("".join(lines(0, 5000)))
    cap_files(tmp_path, max_bytes=CAP)
    age(path)
    before = path.read_bytes()

    for _ in range(3):
        cap_files(tmp_path, max_bytes=CAP)

    assert path.read_bytes() == before
    assert path.stat().st_mtime_ns == LONG_AGO * 1_000_000_000


def test_a_file_is_cut_again_when_it_has_grown_past_the_limit_since(tmp_path: Path) -> None:
    path = tmp_path / "suite.log"
    path.write_text("".join(lines(0, 5000)))
    cap_files(tmp_path, max_bytes=CAP)
    with path.open("ab") as writer:
        writer.write("".join(lines(5000, 5300)).encode())

    cap_files(tmp_path, max_bytes=CAP)

    text = path.read_bytes()
    assert len(text) <= CAP
    assert b"truncated" in marker_of(text)
    assert text.endswith(lines(5299, 5300)[0].encode())


def test_the_hole_an_open_writer_leaves_is_kept_through_one_cut_and_removed_by_the_next(
    tmp_path: Path,
) -> None:
    path = tmp_path / "big.log"
    first, second = lines(0, 1000), lines(1000, 1100)

    # A plain `>`: the writer keeps its offset when the file is cut.
    with path.open("wb") as writer:
        writer.write("".join(first).encode())
        writer.flush()
        cap_files(tmp_path, max_bytes=CAP)
        cut = path.read_bytes()
        assert len(cut) <= CAP
        assert b"truncated" in marker_of(cut)
        assert cut.endswith(first[-1].encode())

        writer.write("".join(second).encode())
        writer.flush()
        assert b"\0" in path.read_bytes(), "the write leaves a hole before it"

        cap_files(tmp_path, max_bytes=CAP)

    repaired = path.read_bytes()
    assert b"\0" not in repaired
    assert len(repaired) <= CAP
    assert b"truncated" in marker_of(repaired)
    assert repaired.endswith(second[-1].encode())


def test_the_watcher_signals_after_a_pass_that_has_cut_the_file(tmp_path: Path) -> None:
    path = tmp_path / "suite.log"
    path.write_text("".join(lines(0, 5000)))

    with watch_folder(tmp_path, max_bytes=CAP, interval=0.01) as passed:
        # The first pass may have begun before the file was written; the second began after.
        for _ in range(2):
            passed.clear()
            assert passed.wait(30), "the watcher never finished a pass"

        assert len(path.read_bytes()) <= CAP
        assert b"truncated" in marker_of(path.read_bytes())
