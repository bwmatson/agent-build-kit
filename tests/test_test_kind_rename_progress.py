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
from agent_build_kit import skills
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
# The tests of the old names write them on purpose: they are what they load, rename or map.
OLD_NAME_TESTS = (
    "test_compat_names.py",
    "test_rename_test_kinds.py",
    "test_rename_test_kinds_forward.py",
    "test_rename_test_kinds_idempotent.py",
    "test_rename_test_kinds_root.py",
    "test_rename_test_kinds_shims.py",
    "test_test_kind_rename_progress.py",
    "test_test_kind_settings_aliases.py",
)


# The two documents that explain the rename write the old names on purpose, as does the
# changelog's entry for it.
EXEMPT_DOCUMENTS = (
    ROOT / "docs" / "agent-efficient-coding-philosophy.md",
    ROOT / "docs" / "risk-tiered-review-design.md",
    ROOT / "CHANGELOG.md",
)
TOP_LEVEL_DOCUMENTS = (ROOT / "README.md", ROOT / "AGENTS.md", ROOT / "CLAUDE.md")


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


def converted_test_directory_files() -> list[Path]:
    """Every text file under `tests/`, bar the tests of the old names."""
    return [p for p in text_files(TESTS) if p.name not in OLD_NAME_TESTS]


def converted_documents() -> list[Path]:
    """The Markdown under `docs/`, the top-level documents and the skills' text."""
    documents = [*sorted((ROOT / "docs").glob("*.md")), *TOP_LEVEL_DOCUMENTS]
    skill_files = text_files(SOURCE / "skills")
    return [p for p in [*documents, *skill_files] if p not in EXEMPT_DOCUMENTS]


def converted_files() -> list[Path]:
    """The pipeline package, the converted source directories, `web/src` and `tests/`."""
    return [
        *converted_pipeline_files(),
        SOURCE / "config.py",
        SOURCE / "installation.py",
        *(p for name in SOURCE_DIRECTORIES for p in text_files(SOURCE / name)),
        *text_files(WEB_SOURCE),
        *converted_test_directory_files(),
        *converted_documents(),
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


def test_no_converted_test_directory_file_is_named_for_an_old_spelling() -> None:
    offenders = [
        str(p.relative_to(TESTS))
        for p in converted_test_directory_files()
        if OLD_SPELLING.search(p.name) and not is_shim_module(p.read_text())
    ]

    assert offenders == []


def test_the_rendered_skills_carry_no_old_spelling() -> None:
    offenders = [name for name in skills.names() if OLD_SPELLING.search(skills.rendered(name))]

    assert offenders == []
