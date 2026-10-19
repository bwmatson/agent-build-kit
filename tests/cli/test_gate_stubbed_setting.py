"""`abk gate` judges a branch as a stubbed build when the installation's setting is on and the
repo's profile supports stubs, and as before otherwise (spec: per-group-commits)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent_build_kit import profiles
from agent_build_kit.cli import main
from agent_build_kit.config import dump
from agent_build_kit.pipeline import gate
from tests.conftest import make_installation


class NoStubs:
    """A profile that declares nothing about stubs."""

    name = "no-stubs"


@pytest.fixture
def asked(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """`check_branch` recording the keyword arguments it was asked with."""
    calls: list[dict[str, Any]] = []

    def record(repo, base, **kwargs):
        calls.append(kwargs)
        return []

    monkeypatch.setattr(gate, "check_branch", record)
    return calls


def gate_in(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, setting: bool, args: list[str]):
    inst = make_installation(tmp_path / "planning", builders={"per_group_commits": setting})
    (inst.root / "abk.yaml").write_text(dump(inst.config))
    app = inst.root / "checkouts" / "app"
    app.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(inst.root)
    return main(["gate", "--repo", str(app), *args])


def test_the_setting_on_with_a_stubbed_profile_runs_the_stubbed_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, asked: list[dict[str, Any]]
) -> None:
    assert gate_in(tmp_path, monkeypatch, setting=True, args=[]) == 0

    assert [call["stubbed"] for call in asked] == [True]


def test_the_setting_off_runs_the_unstubbed_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, asked: list[dict[str, Any]]
) -> None:
    gate_in(tmp_path, monkeypatch, setting=False, args=[])

    assert [call["stubbed"] for call in asked] == [False]


def test_a_profile_that_does_not_support_stubs_runs_the_unstubbed_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, asked: list[dict[str, Any]]
) -> None:
    real = profiles.get
    monkeypatch.setattr(
        profiles, "get", lambda name: NoStubs() if name == "no-stubs" else real(name)
    )

    gate_in(tmp_path, monkeypatch, setting=True, args=["--profile", "no-stubs"])

    assert [call["stubbed"] for call in asked] == [False]
