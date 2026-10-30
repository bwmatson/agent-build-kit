"""A unit-test run's temp folder is traced to its unit from both ends: the unit's log names the
folder and the run, and a failing run's bundle records both (spec:
unit-test-temp-root-short-paths). The folder's own `run.json` is tested with the profile."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import cast

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.flakes import FlakeFound
from agent_build_kit.pipeline.wiring import build_unit_test
from agent_build_kit.profiles.base import ToolchainProfile
from tests.failure_bundle_fakes import BundleMachine, BundleProfile


def failing_run(
    scratch: Path, installation: Installation, directory: Path, messages: list[str]
) -> None:
    unit_test = build_unit_test(
        profile=cast(ToolchainProfile, BundleProfile()),
        run=BundleMachine(scratch, reruns=[1, 1]),
        changed=lambda *a: ["tests/test_one.py"],
        failures_dir=directory,
        installation=installation,
        log=messages.append,
    )
    try:
        unit_test(cwd=scratch, base="main")
    except FlakeFound:
        pass


def test_the_unit_log_names_the_temp_folder_and_its_run(
    scratch: Path, tmp_path: Path, installation: Installation
) -> None:
    messages: list[str] = []

    failing_run(scratch, installation, tmp_path / "bundles", messages)

    (folder,) = installation.pytest_temp_root.iterdir()
    named = [line for line in messages if "temp folder" in line]
    assert named == [f"  unit-test: temp folder {folder} (run {folder.name})"]


def test_the_failure_bundle_names_the_temp_folder_and_its_run(
    scratch: Path, tmp_path: Path, installation: Installation
) -> None:
    directory = tmp_path / "bundles"

    failing_run(scratch, installation, directory, [])

    (folder,) = installation.pytest_temp_root.iterdir()
    (bundle,) = directory.iterdir()
    context = json.loads((bundle / "context.json").read_text())
    assert context["temp_run"] == folder.name
    assert context["temp_folder"] == str(folder)
    assert json.loads((folder / "run.json").read_text())["unit"] == context["unit"]


class Tokens:
    """`uuid.uuid4` giving these tokens in turn (then the last one again when `forever`), and a
    real one for any other caller."""

    def __init__(self, *tokens: str, forever: bool = False) -> None:
        self.tokens = list(tokens)
        self.forever = forever
        self.real = uuid.uuid4

    def __call__(self) -> uuid.UUID:
        if not self.tokens:
            return self.real()
        token = self.tokens[0] if self.forever else self.tokens.pop(0)
        return uuid.UUID(token + "0" * 24)


def test_a_token_whose_folder_exists_is_replaced_by_another(
    scratch: Path,
    tmp_path: Path,
    installation: Installation,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two runs must not share a folder: the first would be recorded as the second's."""
    taken = installation.pytest_temp_root / "aaaaaaaa"
    taken.mkdir(parents=True)
    (taken / "run.json").write_text('{"unit": "other/1"}')
    monkeypatch.setattr(uuid, "uuid4", Tokens("aaaaaaaa", "bbbbbbbb"))
    directory = tmp_path / "bundles"

    failing_run(scratch, installation, directory, [])

    assert sorted(path.name for path in installation.pytest_temp_root.iterdir()) == [
        "aaaaaaaa",
        "bbbbbbbb",
    ]
    assert json.loads((taken / "run.json").read_text()) == {"unit": "other/1"}
    (bundle,) = directory.iterdir()
    assert json.loads((bundle / "context.json").read_text())["temp_run"] == "bbbbbbbb"


def test_a_run_that_cannot_find_a_free_token_says_so_and_does_not_loop(
    scratch: Path,
    tmp_path: Path,
    installation: Installation,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (installation.pytest_temp_root / "aaaaaaaa").mkdir(parents=True)
    monkeypatch.setattr(uuid, "uuid4", Tokens("aaaaaaaa", forever=True))

    with pytest.raises(RuntimeError, match="free run token"):
        failing_run(scratch, installation, tmp_path / "bundles", [])
