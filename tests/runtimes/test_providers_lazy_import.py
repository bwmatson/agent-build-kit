"""The provider's library is imported only when a reading is taken."""

from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path

from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[2]

# Runs in a fresh interpreter with the library hidden, so the real reading function is
# the one asked and nothing in this process has already imported anything.
PROBE = """
import importlib, json, pkgutil, sys
from datetime import UTC, datetime

sys.modules["modal"] = None
import agent_build_kit

failed = {}
for found in pkgutil.walk_packages(agent_build_kit.__path__, "agent_build_kit."):
    if found.name.endswith(".__main__"):
        continue
    try:
        importlib.import_module(found.name)
    except Exception as error:  # noqa: BLE001
        failed[found.name] = f"{type(error).__name__}: {error}"

del sys.modules["modal"]
from agent_build_kit.runtimes import providers

after_import = "modal" in sys.modules


class Finder:
    asked = []

    def find_spec(self, name, path=None, target=None):
        if name.partition(".")[0] == "modal":
            self.asked.append(name)
            raise ModuleNotFoundError(name)
        return None


sys.meta_path.insert(0, Finder())
before_read = list(Finder.asked)
providers.read_usage("modal", budget_usd=200, now=datetime(2026, 10, 14, tzinfo=UTC))
print(json.dumps({
    "failed": failed,
    "after_import": after_import,
    "asked_before_read": before_read,
    "asked_by_read": Finder.asked,
}))
"""


def test_the_library_is_imported_only_by_a_reading() -> None:
    done = subprocess.run(
        [sys.executable, "-c", PROBE], cwd=ROOT, capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stderr

    seen = json.loads(done.stdout.splitlines()[-1])

    assert seen["failed"] == {}
    assert seen["after_import"] is False
    assert seen["asked_before_read"] == []
    assert seen["asked_by_read"] == ["modal"]


def test_the_extra_is_declared_with_an_upper_bound() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())

    extra = [Requirement(e) for e in pyproject["project"]["optional-dependencies"]["modal"]]
    library = next(r for r in extra if r.name == "modal")
    assert any(spec.operator in ("<", "<=", "~=", "==") for spec in library.specifier)
