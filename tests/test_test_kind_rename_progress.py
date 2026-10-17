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

OLD_SPELLING = re.compile(r"tier[-_ ]?[12]", re.IGNORECASE)

SOURCE = Path(agent_build_kit.__file__).parent
PIPELINE = SOURCE / "pipeline"
OLD_PIPELINE_MODULES = ("tier2", "tier2_exclusive", "tier2_holds", "tier2_schedule", "tier2_times")


def converted_pipeline_files() -> list[Path]:
    return sorted(PIPELINE.glob("*.py"))


SOURCE_DIRECTORIES = (
    "cli",
    "forges",
    "graph",
    "infra",
    "init",
    "profiles",
    "recommendations",
    "templates",
    "tracks",
)
ROOT = PIPELINE.parents[2]
WEB_SOURCE = ROOT / "web" / "src"
TESTS = ROOT / "tests"
FIRST_HELPER, LAST_HELPER = "calibration_support", "time_split"
OLD_HELPER_FAKES = (
    "scheduled_tier2_fakes",
    "tier2_base_fakes",
    "tier2_duration_fakes",
    "tier2_failure_fakes",
    "tier2_gate_fakes",
    "tier2_lock_fakes",
    "tier2_park_fakes",
    "tier2_schedule_fakes",
    "tier2_scope_fakes",
    "tier2_wait_fakes",
)


def text_files(folder: Path) -> list[Path]:
    """Every text file under `folder`, bytecode and installed packages left out."""
    found = []
    for path in sorted(folder.rglob("*")):
        if not path.is_file() or {"__pycache__", "node_modules"} & set(path.parts):
            continue
        try:
            path.read_text()
        except UnicodeDecodeError:
            continue
        found.append(path)
    return found


def helper_files() -> list[Path]:
    """The non-test modules at the top of `tests/`, `calibration_support` to `time_split`."""
    helpers = sorted(p for p in TESTS.glob("*.py") if not p.name.startswith("test_"))
    return [p for p in helpers if FIRST_HELPER <= p.stem <= LAST_HELPER]


def converted_files() -> list[Path]:
    """The pipeline package, the converted source directories, `web/src` and the test helpers."""
    return [
        *converted_pipeline_files(),
        SOURCE / "config.py",
        SOURCE / "installation.py",
        *(p for name in SOURCE_DIRECTORIES for p in text_files(SOURCE / name)),
        *text_files(WEB_SOURCE),
        *helper_files(),
    ]


def test_no_converted_pipeline_file_carries_an_old_spelling() -> None:
    offenders = [
        f"{path.relative_to(ROOT)}:{number}"
        for path in converted_files()
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

    python_files = [p for p in converted_files() if p.suffix == ".py"]

    changed = rename_paths(root, python_files, shims=True, dry_run=True)

    assert changed == []


def test_removing_the_shims_would_delete_each_old_pipeline_module() -> None:
    root = PIPELINE.parents[2]

    listed = rename_paths(root, converted_pipeline_files(), remove_shims=True, dry_run=True)

    for old in OLD_PIPELINE_MODULES:
        shim = PIPELINE / f"{old}.py"
        assert is_shim_module(shim.read_text())
        assert shim.relative_to(root) in listed


@pytest.mark.parametrize("old", OLD_HELPER_FAKES)
def test_each_old_fake_module_name_gives_the_objects_of_the_renamed_one(old: str) -> None:
    new = old.replace("tier2", "e2e")

    renamed = importlib.import_module(f"tests.{new}")
    shimmed = importlib.import_module(f"tests.{old}")

    assert shimmed is renamed
