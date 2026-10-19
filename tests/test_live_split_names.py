"""The split names, the runtime markers and the documented example cannot drift apart."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.live_tag_drift import (
    derived_splits,
    documented_splits,
    find_live_modules,
    split_name_drift,
    split_of,
)
from tests.runtime_tag_collection import ROOT

PYPROJECT = ROOT / "pyproject.toml"
DOCUMENT = ROOT / "docs" / "agent-runtimes.md"


def pyproject_with(tmp_path: Path, *markers: str) -> Path:
    path = tmp_path / "pyproject.toml"
    lines = ",\n".join(f'    "{m}: a marker"' for m in ("local_stack", *markers))
    path.write_text(f"[tool.pytest.ini_options]\nmarkers = [\n{lines},\n]\n")
    return path


def document_with(tmp_path: Path, *splits: str) -> Path:
    path = tmp_path / "runtimes.md"
    entries = "".join(f"    {s}:\n      marker: runtime_{s}\n" for s in splits)
    path.write_text(
        "# Runtimes\n\n### This repo's own splits\n\n```yaml\ntests:\n  e2e_splits:\n"
        f"{entries}```\n\n### Another section\n"
    )
    return path


def test_the_splits_of_the_registered_markers_equal_the_documented_splits() -> None:
    assert derived_splits(PYPROJECT) == {"acp", "claude_code"}
    assert documented_splits(DOCUMENT) == derived_splits(PYPROJECT)
    assert split_name_drift(PYPROJECT, DOCUMENT) == []


def test_matching_markers_and_splits_name_nothing(tmp_path: Path) -> None:
    pyproject = pyproject_with(tmp_path, "runtime_a", "runtime_b")
    document = document_with(tmp_path, "a", "b")

    assert split_name_drift(pyproject, document) == []


def test_an_extra_marker_is_named(tmp_path: Path) -> None:
    pyproject = pyproject_with(tmp_path, "runtime_a", "runtime_foo")
    document = document_with(tmp_path, "a")

    found = split_name_drift(pyproject, document)

    assert len(found) == 1
    assert "foo" in found[0]


def test_an_extra_split_is_named(tmp_path: Path) -> None:
    pyproject = pyproject_with(tmp_path, "runtime_a")
    document = document_with(tmp_path, "a", "bar")

    found = split_name_drift(pyproject, document)

    assert len(found) == 1
    assert "bar" in found[0]


def test_every_tagged_live_test_of_the_kit_is_in_one_derived_split(
    pytester: pytest.Pytester,
) -> None:
    modules = find_live_modules(ROOT / "tests")
    items, _ = pytester.inline_genitems(*(str(m) for m in modules))
    splits = derived_splits(PYPROJECT) | {"rest"}

    assert items
    assert {split_of(item) for item in items} <= splits
    assert {split_of(item) for item in items} - {"rest"}
