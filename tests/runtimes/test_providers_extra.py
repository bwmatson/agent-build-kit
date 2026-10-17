"""The provider's library is an optional extra that brings `acp`, and the lock holds it."""

from __future__ import annotations

import dataclasses
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement

from agent_build_kit.runtimes.providers import read_modal_summary

ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text())
LOCK = tomllib.loads((ROOT / "uv.lock").read_text())
OWN_NAME = PYPROJECT["project"]["name"]


def requirements(entries: list[str]) -> list[Requirement]:
    return [Requirement(entry) for entry in entries]


def own_lock_package() -> dict:
    return next(package for package in LOCK["package"] if package["name"] == OWN_NAME)


def assert_lock_is_current() -> None:
    uv = shutil.which("uv")
    assert uv is not None

    done = subprocess.run(
        [uv, "lock", "--check", "--offline"], cwd=ROOT, capture_output=True, text=True, check=False
    )

    assert done.returncode == 0, done.stderr


def test_the_development_group_includes_the_modal_extra() -> None:
    own = [r for r in requirements(PYPROJECT["dependency-groups"]["dev"]) if r.name == OWN_NAME]

    assert any("modal" in r.extras for r in own)


def test_the_lock_holds_the_library_and_the_extra() -> None:
    assert any(package["name"] == "modal" for package in LOCK["package"])
    assert "modal" in own_lock_package()["metadata"]["provides-extras"]
    assert_lock_is_current()


def test_the_modal_extra_names_the_kit_with_the_acp_extra_so_it_brings_acp() -> None:
    extra = requirements(PYPROJECT["project"]["optional-dependencies"]["modal"])

    assert any(r.name == OWN_NAME and "acp" in r.extras for r in extra)
    assert any(r.name == "modal" for r in extra)
    assert "acp" in PYPROJECT["project"]["optional-dependencies"]


def test_the_lock_lists_both_extras() -> None:
    assert {"acp", "modal"} <= set(own_lock_package()["metadata"]["provides-extras"])


def test_the_library_is_importable_in_the_development_environment() -> None:
    import importlib

    types = importlib.import_module("modal.types")

    fields = {field.name for field in dataclasses.fields(types.WorkspaceBillingSummary)}
    assert {"start", "end", "metered_cost"} <= fields


def test_the_guard_trips_when_the_real_reading_function_is_called() -> None:
    with pytest.raises(pytest.fail.Exception, match="a unit-test test called the real provider"):
        read_modal_summary()
