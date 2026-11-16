"""The package table in `docs/designs/orchestration.md` puts the runtimes, sandboxes, profiles
and hooks under the core, and no module under two packages (spec: kit-packages)."""

from __future__ import annotations

import re

import pytest

from tests.doc_text import ROOT

DESIGN = ROOT / "docs" / "designs" / "orchestration.md"
PACKAGES = ("core", "orchestrator", "worker")
CORE_MODULES = ("runtimes", "sandboxes", "profiles", "hooks")


def package_table() -> dict[str, str]:
    """The `Holds` cell of each row of the table under `## Three packages`, keyed by package."""
    text = DESIGN.read_text(encoding="utf-8")
    section = re.search(r"^## Three packages\n(.*?)(?=^## )", text, re.M | re.S)
    assert section, "the `## Three packages` section is missing"
    rows: dict[str, str] = {}
    for line in section.group(1).splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if line.startswith("|") and cells[0] in PACKAGES:
            rows[cells[0]] = cells[1].lower()
    assert set(rows) == set(PACKAGES), f"the table has rows for {sorted(rows)}"
    return rows


def mentions(cell: str, module: str) -> bool:
    return re.search(rf"\b{module}\b", cell) is not None


@pytest.mark.parametrize("module", CORE_MODULES)
def test_the_table_lists_the_module_under_the_core(module: str) -> None:
    assert mentions(package_table()["core"], module)


@pytest.mark.parametrize("module", CORE_MODULES)
def test_the_table_lists_the_module_under_no_other_package(module: str) -> None:
    rows = package_table()
    others = [name for name in PACKAGES if name != "core" and mentions(rows[name], module)]
    assert others == []
