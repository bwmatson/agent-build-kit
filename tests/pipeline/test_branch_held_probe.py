"""Asking whether a branch is held never takes the branch, so a build starting at the same
moment is not turned away by the question (spec: unit-scheduling)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from agent_build_kit.pipeline import workspaces
from agent_build_kit.pipeline.workspaces import branch_held

BRANCH = "spec/add-marker/1"


class ClaimSpy:
    """`workspaces.os` with the opens that claim a lock file (`O_EXCL`) recorded."""

    def __init__(self) -> None:
        self.claims: list[str] = []

    def __getattr__(self, name: str) -> object:
        return getattr(os, name)

    def open(self, path: str | os.PathLike[str], flags: int, *args: int) -> int:
        if flags & os.O_EXCL:
            self.claims.append(str(path))
        return os.open(path, flags, *args)


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> ClaimSpy:
    spy = ClaimSpy()
    monkeypatch.setattr(workspaces, "os", spy)
    return spy


def test_asking_about_a_free_branch_claims_no_lock_file(tmp_path: Path, spy: ClaimSpy) -> None:
    assert branch_held(BRANCH, root=tmp_path) is False

    assert spy.claims == []
