"""Clones: runs of identical tokens that occur at two places in the source files."""

import io
import tokenize
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path

from agent_build_kit.model import Frozen

DROPPED = frozenset(
    {
        tokenize.ENCODING,
        tokenize.NEWLINE,
        tokenize.NL,
        tokenize.INDENT,
        tokenize.DEDENT,
        tokenize.COMMENT,
        tokenize.ENDMARKER,
    }
)
MODULUS = (1 << 61) - 1
BASE = 1_000_003

Position = tuple[int, int]


class ClonePlace(Frozen):
    """Where one copy of a clone sits: a file and its first and last line."""

    path: str
    first_line: int
    last_line: int


class Clone(Frozen):
    """A run of at least the clone length that occurs at two places."""

    places: tuple[ClonePlace, ClonePlace]


class TokenStream(Frozen):
    """One file's kept tokens: an id for each token's type and text, and its first and last line."""

    path: str
    ids: tuple[int, ...]
    spans: tuple[tuple[int, int], ...]


def find_clones(
    root: Path, paths: list[str], added_lines: Mapping[str, set[int]], clone_tokens: int
) -> list[Clone]:
    """The clones among the files `paths` (relative to `root`) of at least `clone_tokens` tokens
    with a token on an added line (`added_lines`: path to line numbers) at either place."""
    vocabulary: dict[tuple[int, str], int] = {}
    streams = [
        stream for path in paths if (stream := _read_stream(root, path, vocabulary)) is not None
    ]
    pairs = _matching_pairs(streams, clone_tokens)
    clones = []
    for first, second, length in _runs(pairs, streams, clone_tokens):
        places = (_place(streams, first, length), _place(streams, second, length))
        if any(_holds_added(streams, at, length, added_lines) for at in (first, second)):
            clones.append(Clone(places=places))
    return clones


def _read_stream(
    root: Path, path: str, vocabulary: dict[tuple[int, str], int]
) -> TokenStream | None:
    """The kept tokens of the file, or None when it cannot be read or tokenized."""
    try:
        source = (root / path).read_text(encoding="utf-8")
        tokens = [
            token
            for token in tokenize.generate_tokens(io.StringIO(source).readline)
            if token.type not in DROPPED
        ]
    except (OSError, UnicodeDecodeError, tokenize.TokenError, SyntaxError):
        return None
    ids = tuple(
        vocabulary.setdefault((token.type, token.string), len(vocabulary)) for token in tokens
    )
    spans = tuple((token.start[0], token.end[0]) for token in tokens)
    return TokenStream(path=path, ids=ids, spans=spans)


def _window_hashes(ids: tuple[int, ...], length: int) -> list[int]:
    """The rolling hash of each window of `length` ids."""
    if len(ids) < length:
        return []
    top = pow(BASE, length - 1, MODULUS)
    value = 0
    for item in ids[:length]:
        value = (value * BASE + item + 1) % MODULUS
    hashes = [value]
    for start in range(1, len(ids) - length + 1):
        value = (
            (value - (ids[start - 1] + 1) * top) * BASE + ids[start + length - 1] + 1
        ) % MODULUS
        hashes.append(value)
    return hashes


def _matching_pairs(streams: list[TokenStream], length: int) -> set[tuple[Position, Position]]:
    """Each pair of window starts, the earlier first, whose `length` tokens are equal."""
    buckets: dict[int, list[Position]] = defaultdict(list)
    for index, stream in enumerate(streams):
        for start, hashed in enumerate(_window_hashes(stream.ids, length)):
            buckets[hashed].append((index, start))
    pairs = set()
    for places in buckets.values():
        for position, first in enumerate(places):
            for second in places[position + 1 :]:
                if _window(streams, first, length) == _window(streams, second, length):
                    pairs.add((first, second))
    return pairs


def _window(streams: list[TokenStream], at: Position, length: int) -> tuple[int, ...]:
    return streams[at[0]].ids[at[1] : at[1] + length]


def _runs(
    pairs: set[tuple[Position, Position]], streams: list[TokenStream], length: int
) -> list[tuple[Position, Position, int]]:
    """The maximal runs of consecutive windows of one pair of places, as the two starts and the
    run's token count, cut short where the two places of one file would overlap."""
    runs = []
    for first, second in sorted(pairs):
        if ((first[0], first[1] - 1), (second[0], second[1] - 1)) in pairs:
            continue
        extra = 0
        while ((first[0], first[1] + extra + 1), (second[0], second[1] + extra + 1)) in pairs:
            extra += 1
        run = length + extra
        if first[0] == second[0]:
            run = min(run, second[1] - first[1])
        if run >= length:
            runs.append((first, second, run))
    return runs


def _place(streams: list[TokenStream], at: Position, length: int) -> ClonePlace:
    stream = streams[at[0]]
    return ClonePlace(
        path=stream.path,
        first_line=stream.spans[at[1]][0],
        last_line=stream.spans[at[1] + length - 1][1],
    )


def _holds_added(
    streams: list[TokenStream], at: Position, length: int, added_lines: Mapping[str, set[int]]
) -> bool:
    stream = streams[at[0]]
    added = added_lines.get(stream.path, set())
    return any(
        line in added
        for first, last in stream.spans[at[1] : at[1] + length]
        for line in range(first, last + 1)
    )
