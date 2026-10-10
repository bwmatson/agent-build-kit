"""Cassettes on disk: one gzip-compressed JSON file per call, at
`<directory>/<test id, path-safe>/<call index>-<key prefix>.json.gz`."""

from __future__ import annotations

import gzip
import re
from pathlib import Path

from agent_build_kit.replay.models import Cassette

_SUFFIX = ".json.gz"
_PREFIX = 12


def test_directory(directory: Path, test_id: str) -> Path:
    return directory / re.sub(r"[^A-Za-z0-9_.-]+", "_", test_id)


def cassette_path(directory: Path, cassette: Cassette) -> Path:
    name = f"{cassette.call_index:04d}-{cassette.key[:_PREFIX]}{_SUFFIX}"
    return test_directory(directory, cassette.test_id) / name


def write_cassette(directory: Path, cassette: Cassette) -> Path:
    path = cassette_path(directory, cassette)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(cassette.model_dump_json().encode(), mtime=0))
    return path


def load_cassette(path: Path) -> Cassette:
    return Cassette.model_validate_json(gzip.decompress(path.read_bytes()))


def find_cassette(directory: Path, test_id: str, key: str) -> Cassette | None:
    """The cassette of `test_id` recorded under `key`, if there is one."""
    for path in sorted(test_directory(directory, test_id).glob(f"*-{key[:_PREFIX]}{_SUFFIX}")):
        if (cassette := load_cassette(path)).key == key:
            return cassette
    return None


def read_cassettes(directory: Path) -> list[Cassette]:
    """Every cassette under `directory`, in test and call order."""
    found = [load_cassette(path) for path in directory.rglob(f"*{_SUFFIX}")]
    return sorted(found, key=lambda cassette: (cassette.test_id, cassette.call_index))
