"""The words a wait carries are not part of what the decision log records: a restart, or a hold
whose reason or deadline changes, appends nothing while the reason and what it waits on stand."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_build_kit.pipeline.vocabulary import WaitReason
from agent_build_kit.pipeline.wait_log import Wait, WaitRecorder
from tests.fake_clock import install

UNIT = "add-marker/1"


def lines_of(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def split_wait(detail: str) -> dict[str, Wait]:
    return {UNIT: Wait(reason=WaitReason.SPLIT, detail=detail)}


def test_a_restarted_recorder_appends_nothing_for_the_same_reason_with_words(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install(monkeypatch)
    path = tmp_path / "decisions.jsonl"
    WaitRecorder(path, print).record(split_wait(""), tick="1")

    WaitRecorder(path, print).record(split_wait("waiting for e2e-test split acp: out"), tick="2")

    assert [line["reason"] for line in lines_of(path)] == ["split"]


def test_a_change_of_the_words_alone_appends_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install(monkeypatch)
    path = tmp_path / "decisions.jsonl"
    recorder = WaitRecorder(path, print)
    recorder.record(split_wait("until 10:00"), tick="1")

    recorder.record(split_wait("until 11:00"), tick="2")

    assert len(lines_of(path)) == 1
