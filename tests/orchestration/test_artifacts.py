"""The Artifacts interface: one conformance suite that takes an implementation.

The suite runs here against the local implementation in a temporary state directory; the
Azure implementation is added to the `artifacts` fixture's params by the group that builds it.
The local-only cases pin that a key maps to the file the writers use today.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from agent_build_kit import orchestration
from agent_build_kit.installation import Installation
from agent_build_kit.orchestration.artifacts import (
    INTERFACE,
    Artifacts,
    MissingArtifact,
)
from agent_build_kit.pipeline import run_log, spec_snapshot, transcript
from tests.conftest import make_installation
from tests.redaction_fakes import NAME, SECRET, known


@pytest.fixture(autouse=True)
def fresh_registry() -> Iterator[None]:
    orchestration.reset()
    yield
    orchestration.reset()


@pytest.fixture
def local_installation(tmp_path: Path) -> Installation:
    return make_installation(tmp_path / "planning", deployment=dict(kind="local"))


@pytest.fixture
def local_artifacts(local_installation: Installation) -> Iterator[Artifacts]:
    with known():
        yield orchestration.get(INTERFACE, local_installation)


@pytest.fixture(params=["local"])
def artifacts(request: pytest.FixtureRequest, local_artifacts: Artifacts) -> Artifacts:
    return local_artifacts


def test_a_value_put_under_a_key_is_got_back(artifacts: Artifacts) -> None:
    artifacts.put("unit-logs/a.log", "hello\n")

    assert artifacts.get("unit-logs/a.log") == b"hello\n"


def test_list_returns_the_keys_under_the_prefix_and_no_others(artifacts: Artifacts) -> None:
    for key in ("transcripts/a.jsonl", "transcripts/b.jsonl", "transcripts-old/c", "unit-logs/d"):
        artifacts.put(key, "x")

    assert artifacts.list("transcripts/") == ["transcripts/a.jsonl", "transcripts/b.jsonl"]


def test_delete_removes_the_keys_under_the_prefix_and_keeps_the_rest(artifacts: Artifacts) -> None:
    for key in ("transcripts/a.jsonl", "transcripts/b.jsonl", "unit-logs/d"):
        artifacts.put(key, "x")

    artifacts.delete("transcripts/")

    assert artifacts.list("") == ["unit-logs/d"]


def test_a_writers_flushed_lines_are_read_before_it_closes(artifacts: Artifacts) -> None:
    writer = artifacts.writer("transcripts/live.jsonl")
    try:
        writer.write("one\n")
        writer.write("two\n")
        writer.flush()

        assert artifacts.get("transcripts/live.jsonl") == b"one\ntwo\n"
    finally:
        writer.close()


def test_a_writer_appends_to_what_an_earlier_writer_left(artifacts: Artifacts) -> None:
    first = artifacts.writer("unit-logs/a.log")
    first.write("one\n")
    first.close()
    second = artifacts.writer("unit-logs/a.log")
    second.write("two\n")
    second.close()

    assert artifacts.get("unit-logs/a.log") == b"one\ntwo\n"


def test_a_key_reads_as_empty_once_a_writer_has_opened_it(artifacts: Artifacts) -> None:
    writer = artifacts.writer("transcripts/live.jsonl")
    try:
        assert artifacts.get("transcripts/live.jsonl") == b""
    finally:
        writer.close()


def test_a_text_value_holding_a_registered_secret_is_stored_redacted(artifacts: Artifacts) -> None:
    artifacts.put("unit-logs/a.log", f"token {SECRET} used")

    assert artifacts.get("unit-logs/a.log").decode() == f"token [redacted:{NAME}] used"


def test_a_writers_text_holding_a_registered_secret_is_stored_redacted(
    artifacts: Artifacts,
) -> None:
    writer = artifacts.writer("unit-logs/a.log")
    writer.write(f"token {SECRET}\n")
    writer.close()

    assert artifacts.get("unit-logs/a.log").decode() == f"token [redacted:{NAME}]\n"


def test_bytes_are_stored_unchanged(artifacts: Artifacts) -> None:
    payload = b"\x00\xff" + SECRET.encode() + b"\x01"

    artifacts.put("spec-snapshots/u/r/blob", payload)

    assert artifacts.get("spec-snapshots/u/r/blob") == payload


def test_a_missing_key_is_reported_as_missing_not_as_empty(artifacts: Artifacts) -> None:
    with pytest.raises(MissingArtifact):
        artifacts.get("unit-logs/none.log")


@pytest.mark.parametrize(
    ("key", "directory"),
    [
        ("unit-logs/a.log", run_log.run_log_dir),
        ("test-failures/a.txt", run_log.failure_bundles_dir),
        ("transcripts/a.jsonl", transcript.transcript_dir),
        (
            "spec-snapshots/u/r/a.md",
            lambda state_dir: spec_snapshot.snapshot_dir(state_dir, "u", "r"),
        ),
    ],
)
def test_a_key_maps_to_the_file_the_writing_modules_use_today(
    local_artifacts: Artifacts,
    local_installation: Installation,
    key: str,
    directory: Callable[[Path], Path],
) -> None:
    local_artifacts.put(key, "body")

    expected = directory(local_installation.state_dir) / key.rsplit("/", 1)[1]
    assert expected.read_text() == "body"


@pytest.mark.parametrize(
    ("key", "directory"),
    [
        ("unit-logs/old.log", run_log.run_log_dir),
        ("transcripts/old.jsonl", transcript.transcript_dir),
    ],
)
def test_a_file_written_before_the_change_is_read_by_its_key(
    local_artifacts: Artifacts,
    local_installation: Installation,
    key: str,
    directory: Callable[[Path], Path],
) -> None:
    folder = directory(local_installation.state_dir)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / key.rsplit("/", 1)[1]).write_text("earlier\n")

    assert local_artifacts.get(key) == b"earlier\n"
    assert key in local_artifacts.list(key.split("/")[0] + "/")
