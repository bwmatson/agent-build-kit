"""Cassettes on disk: one gzip-compressed JSON file per call."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.replay.models import Cassette


def read_cassettes(directory: Path) -> list[Cassette]:
    """Every cassette under `directory`, in test and call order."""
    raise NotImplementedError
