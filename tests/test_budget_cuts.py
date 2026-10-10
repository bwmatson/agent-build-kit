"""The shared cuts: unchanged when they fit, never over the size, closed when open."""

from __future__ import annotations

import pytest

from agent_build_kit.budget import cut_head, cut_middle, cut_tail

CUTS = [cut_head, cut_tail, cut_middle]


def lined(count: int, width: int = 30) -> str:
    return "\n".join(f"line {number:04d} " + "x" * width for number in range(count))


@pytest.mark.parametrize("cut", CUTS)
@pytest.mark.parametrize("boundary", ["char", "line", "paragraph"])
def test_a_text_that_fits_is_unchanged(cut, boundary) -> None:
    text = "one\n\ntwo\nthree"
    assert cut(text, len(text), boundary) == text
    assert cut(text, len(text) + 50, boundary) == text


@pytest.mark.parametrize("cut", CUTS)
@pytest.mark.parametrize("boundary", ["char", "line", "paragraph"])
@pytest.mark.parametrize("size", [0, 1, 10, 100, 333, 1000])
def test_a_cut_never_exceeds_the_size(cut, boundary, size) -> None:
    text = "\n\n".join(lined(5) for _ in range(40))
    assert len(cut(text, size, boundary, marker="[cut]")) <= size


def test_head_keeps_the_start_and_drops_the_end() -> None:
    got = cut_head(lined(100), 200, "line")
    assert got.startswith("line 0000 ")
    assert "line 0099" not in got


def test_tail_keeps_the_end_and_drops_the_start() -> None:
    got = cut_tail(lined(100), 200, "line")
    assert "line 0099" in got
    assert "line 0000" not in got


def test_middle_keeps_both_ends() -> None:
    got = cut_middle(lined(100), 400, "line", marker="[cut]")
    assert got.startswith("line 0000 ")
    assert "line 0099" in got
    assert "line 0050" not in got
    assert "[cut]" in got


def test_a_line_cut_falls_between_lines() -> None:
    text = lined(100)
    given = set(text.splitlines())
    for cut in (cut_head, cut_tail):
        assert set(cut(text, 250, "line").splitlines()) <= given


def test_a_paragraph_cut_falls_between_paragraphs() -> None:
    paragraphs = [f"paragraph {n}\nsecond line {n}" for n in range(50)]
    text = "\n\n".join(paragraphs)
    for cut in (cut_head, cut_tail):
        got = cut(text, 200, "paragraph")
        assert got
        assert set(got.split("\n\n")) <= set(paragraphs)


def test_a_char_cut_may_fall_inside_a_line() -> None:
    assert cut_head("x" * 100, 40, "char") == "x" * 40
    assert cut_tail("x" * 100, 40, "char") == "x" * 40


def test_the_marker_is_within_the_size() -> None:
    got = cut_head(lined(100), 300, "line", marker="[cut]")
    assert got.endswith("[cut]")
    assert len(got) <= 300
    got = cut_tail(lined(100), 300, "line", marker="[cut]")
    assert got.startswith("[cut]")
    assert len(got) <= 300


def test_a_head_cut_inside_a_code_fence_closes_it() -> None:
    text = "intro\n\n```\n" + lined(100) + "\n```\n\nafter"
    got = cut_head(text, 300, "line", marker="[cut]")
    assert len(got) <= 300
    assert got.count("```") % 2 == 0
    assert "after" not in got


def test_a_tail_cut_that_starts_inside_a_fence_leaves_it_balanced() -> None:
    text = "intro\n\n```\n" + lined(100) + "\n```\n\nafter"
    got = cut_tail(text, 300, "line")
    assert len(got) <= 300
    assert got.count("```") % 2 == 0


def test_a_head_cut_inside_a_details_block_closes_it() -> None:
    text = "<details>\n<summary>Full</summary>\n\n" + lined(100) + "\n\n</details>\n\nafter"
    got = cut_head(text, 300, "line", marker="[cut]")
    assert len(got) <= 300
    assert got.count("<details") == got.count("</details>")


def test_a_fence_inside_a_details_block_are_both_closed() -> None:
    text = "<details>\n<summary>Full</summary>\n\n```\n" + lined(100) + "\n```\n\n</details>\n"
    got = cut_head(text, 300, "line")
    assert len(got) <= 300
    assert got.count("```") % 2 == 0
    assert got.count("<details") == got.count("</details>")
    assert got.rstrip().endswith("</details>")
