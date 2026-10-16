"""How far the test-kind rename has got (spec: test-kind-names, "A slice leaves the rest importing")

Each slice of the rename extends `SLICES` with the files it converts; the last slice replaces this
file with the strict guard.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

import agent_build_kit
from agent_build_kit.rename_test_kinds import (
    FORWARD_MARKER,
    SHIM_MARKER,
    is_shim_module,
    rename_paths,
)

OLD_SPELLING = re.compile(r"tier ?[12]", re.IGNORECASE)

PIPELINE = Path(agent_build_kit.__file__).parent / "pipeline"
PIPELINE_FIRST, PIPELINE_LAST = "archive.py", "verify.py"

OLD_PIPELINE_MODULES = ("tier2", "tier2_exclusive", "tier2_holds", "tier2_schedule", "tier2_times")


def converted_pipeline_files() -> list[Path]:
    return [
        path
        for path in sorted(PIPELINE.glob("*.py"))
        if PIPELINE_FIRST <= path.name <= PIPELINE_LAST
    ]


def test_no_converted_pipeline_file_carries_an_old_spelling() -> None:
    offenders = [
        f"{path.name}:{number}"
        for path in converted_pipeline_files()
        if not is_shim_module(path.read_text())
        for number, line in enumerate(path.read_text().splitlines(), start=1)
        if OLD_SPELLING.search(line) and SHIM_MARKER not in line and FORWARD_MARKER not in line
    ]

    assert offenders == []


@pytest.mark.parametrize("old", OLD_PIPELINE_MODULES)
def test_each_old_pipeline_module_name_gives_the_objects_of_the_renamed_one(old: str) -> None:
    new = old.replace("tier2", "e2e")

    renamed = importlib.import_module(f"agent_build_kit.pipeline.{new}")
    shimmed = importlib.import_module(f"agent_build_kit.pipeline.{old}")

    assert shimmed is renamed


def test_the_tool_has_nothing_left_to_change_in_the_converted_files() -> None:
    root = PIPELINE.parents[2]

    changed = rename_paths(root, converted_pipeline_files(), shims=True, dry_run=True)

    assert changed == []


def test_removing_the_shims_would_delete_each_old_pipeline_module() -> None:
    root = PIPELINE.parents[2]

    listed = rename_paths(root, converted_pipeline_files(), remove_shims=True, dry_run=True)

    for old in OLD_PIPELINE_MODULES:
        shim = PIPELINE / f"{old}.py"
        assert is_shim_module(shim.read_text())
        assert shim.relative_to(root) in listed
