"""Clones: runs of identical tokens at two places, reported when either holds an added line."""

from pathlib import Path

import pytest

from agent_build_kit.quality.clones import find_clones

CLONE_TOKENS = 50
Place = tuple[str, int, int]


def run_lines(
    tokens: int,
    *,
    indent: str = "",
    noisy: bool = False,
    middle: str | None = None,
    fill: str | None = None,
) -> list[str]:
    """Source lines whose statement is exactly `tokens` kept tokens: `data = [1, 2, ...]`, with
    one more token (`not`) when `tokens` is even. `noisy` adds comments and blank lines, `middle`
    replaces the middle element, `fill` every element."""
    even = tokens % 2 == 0
    count = (tokens - (4 if even else 3)) // 2
    values = [fill or str(number) for number in range(1, count + 1)]
    if middle is not None:
        values[count // 2] = middle
    note = "  # a note" if noisy else ""
    lines = [f"{indent}data = {'not ' if even else ''}[{note}"]
    for position, value in enumerate(values):
        lines.append(f"{indent}    {value}{',' if position < count - 1 else ''}{note}")
        if noisy:
            lines.append("")
    lines.append(f"{indent}]{note}")
    return lines


def text_of(lines: list[str]) -> str:
    return "\n".join(lines) + "\n"


def surrounded(before: str, run: list[str], after: str) -> tuple[str, Place]:
    """A file of `before`, the run and `after`, and the run's line span (path left empty)."""
    return text_of([before, *run, after]), ("", 2, 1 + len(run))


def summary(found: list) -> list[list[Place]]:
    return sorted(
        sorted((place.path, place.first_line, place.last_line) for place in clone.places)
        for clone in found
    )


def two_files(
    first: list[str],
    second: list[str],
    *,
    indent_second: bool = False,
    added: tuple[str, ...] = ("a.py",),
) -> tuple[dict[str, str], dict[str, set[int]], list[list[Place]]]:
    """Two files sharing `first` and `second`, which are equal tokens, the second written inside
    a function when `indent_second`; the first line of each run in `added`'s files is added."""
    text_a, (_, start_a, end_a) = surrounded("alpha = 1", first, "omega = 1")
    if indent_second:
        text_b = text_of(["def other():", *second, "tail = 2"])
        start_b, end_b = 2, 1 + len(second)
    else:
        text_b, (_, start_b, end_b) = surrounded("beta = 2", second, "psi = 2")
    starts = {"a.py": start_a, "b.py": start_b}
    expected = [sorted([("a.py", start_a, end_a), ("b.py", start_b, end_b)])]
    return {"a.py": text_a, "b.py": text_b}, {name: {starts[name]} for name in added}, expected


def shared_case(tokens: int = CLONE_TOKENS, **kwargs) -> tuple:
    run = run_lines(tokens)
    return two_files(run, run, **kwargs)


def noisy_case() -> tuple:
    plain, noisy = run_lines(CLONE_TOKENS), run_lines(CLONE_TOKENS, indent="    ", noisy=True)
    files, added, _ = two_files(plain, noisy, indent_second=True)
    span_b = (2, 1 + len(noisy))
    return files, added, [sorted([("a.py", 2, 1 + len(plain)), ("b.py", *span_b)])]


def names_differ_case() -> tuple:
    return two_files(
        run_lines(CLONE_TOKENS, middle="total"), run_lines(CLONE_TOKENS, middle="count")
    )[:2] + ([],)


def repeated_in_one_file_case(fill: str | None) -> tuple:
    """One file holding the run twice (separated by other tokens) or, with `fill`, one periodic
    run whose copies would overlap."""
    if fill is not None:
        text = text_of(run_lines(62, fill=fill))
        return {"a.py": text}, {"a.py": {1}}, []
    run = run_lines(CLONE_TOKENS)
    lines = ["first = 1", *run, "third = 1", "second = 2", *run, "fourth = 2"]
    second_start = len(run) + 4
    expected = [
        sorted([("a.py", 2, 1 + len(run)), ("a.py", second_start, second_start + len(run) - 1)])
    ]
    return {"a.py": text_of(lines)}, {"a.py": {2}}, expected


CASES = {
    "the same tokens apart from comments, blank lines and indentation": noisy_case(),
    "one token short of the clone length": shared_case(CLONE_TOKENS - 1)[:2] + ([],),
    "a run whose names differ in the middle": names_differ_case(),
    "a run repeated at overlapping places in one file": repeated_in_one_file_case("1"),
    "a run repeated at separate places in one file": repeated_in_one_file_case(None),
    "no added line at either place": shared_case(added=())[:2] + ([],),
    "an added line at the first place only": shared_case(added=("a.py",)),
    "an added line at the second place only": shared_case(added=("b.py",)),
    "a run longer than the clone length, reported once": shared_case(80),
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_a_run_of_equal_tokens_is_a_clone_by_the_rules_of_the_measure(
    case: str, tmp_path: Path
) -> None:
    files, added, expected = CASES[case]
    for name, text in files.items():
        (tmp_path / name).write_text(text)

    found = find_clones(tmp_path, sorted(files), added, CLONE_TOKENS)

    assert summary(found) == expected
