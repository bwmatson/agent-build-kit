"""A repository with, or without, a `tests.replay` section, and cassettes in it."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.config import ReplayConfig, RepoConfig, TestsConfig
from agent_build_kit.replay.models import Cassette
from agent_build_kit.replay.state import ReplayState, write_state
from agent_build_kit.replay.store import write_cassette
from tests.factories import init_repo
from tests.replay.support import relative

DIRECTORY = Path("tests/cassettes")
REVIEW_AFTER_RUNS = 5


def replay_repo(path: Path, *, section: bool = True) -> tuple[RepoConfig, Path]:
    """A checkout, its config, and the directory its cassettes belong in."""
    app = init_repo(path)
    replay = ReplayConfig(directory=DIRECTORY, review_after_runs=REVIEW_AFTER_RUNS)
    tests = TestsConfig(replay=replay if section else None)
    return RepoConfig(path=app, slug="example/app", tests=tests), app / DIRECTORY


def store(directory: Path, *cassettes: Cassette, unreviewed_runs: int = 0) -> list[str]:
    """Write `cassettes`, each waiting for `unreviewed_runs` runs; their names under `directory`."""
    for cassette in cassettes:
        write_cassette(directory, cassette)
    names = [relative(directory, cassette) for cassette in cassettes if cassette.needs_review]
    write_state(directory, ReplayState(unreviewed_runs={name: unreviewed_runs for name in names}))
    return names
