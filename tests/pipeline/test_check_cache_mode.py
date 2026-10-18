"""The push gate's result cache is keyed by mode (spec: test-stubs).

A result cached by an unstubbed run never ran types, so a stubbed run of the same patch must
not reuse it; one cached by a stubbed run is reused by the next stubbed run, restack or not.
"""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.check_runner import CheckCache
from tests.stub_gate_support import (
    ModeProfile,
    judged,
    repo,  # noqa: F401  (the fixture)
    restack_onto_moved_main,
    two_pairs,
)


def test_a_result_cached_by_an_unstubbed_run_is_not_reused_by_a_stubbed_run(
    repo: Path,  # noqa: F811 — fixture
    tmp_path: Path,
) -> None:
    two_pairs(repo)
    cache = CheckCache(tmp_path / "cache.json")
    assert judged(repo, ModeProfile(), cache=cache) == []
    failing_types = ModeProfile(bad_types="tests/test_b.py")

    problems = judged(repo, failing_types, cache=cache, stubbed=True)

    assert problems, "the checks ran again, with types"
    assert failing_types.cleans == [True, True]


def test_a_result_cached_by_a_stubbed_run_is_reused_by_the_next_after_a_restack(
    repo: Path,  # noqa: F811 — fixture
    tmp_path: Path,
) -> None:
    two_pairs(repo)
    cache = CheckCache(tmp_path / "cache.json")
    first = ModeProfile()
    assert judged(repo, first, cache=cache, stubbed=True) == []
    assert first.cleans == [True, True]
    restack_onto_moved_main(repo)
    next_run = ModeProfile(bad_types="tests/test_b.py")

    assert judged(repo, next_run, cache=cache, stubbed=True) == []

    assert next_run.cleans == [], "nothing was run: both commits were found by content"
