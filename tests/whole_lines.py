"""What a tail cut of a long, many-lined output must look like, shared by the tests of the cuts."""

from __future__ import annotations


def long_output_lines(count: int) -> list[str]:
    return [f"console line {n:05d} of a long output" for n in range(count)]


def assert_tail_of_whole_lines(kept: str, original: list[str], budget: int) -> None:
    """`kept` is at most `budget` characters, ends where `original` ends, and cuts no line."""
    assert 0 < len(kept) <= budget
    assert kept.splitlines()[-1] == original[-1], "the end of the output is kept"
    assert set(kept.splitlines()) <= set(original), "no line starts or ends in the middle"
