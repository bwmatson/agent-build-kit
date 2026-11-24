"""The packages of the kit's uv workspace, defined once for the tests of its layout.

`PACKAGES` maps each package's name to its project folder (the root project and each package
under `packages/`), derived from `tests/tracked_files.py`'s `source_trees`, which is also how a
guard walks the source, so a new package is picked up without an edit here.
`shared_init_files` names a folder's `__init__.py` that more than one package ships (a package
split across projects keeps it in one only).
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from tests.tracked_files import ROOT, source_trees

PACKAGE_NAME = "agent_build_kit"
# Derived from the source trees, so the two cannot disagree about where a package's modules sit.
PACKAGES: dict[str, Path] = {
    "root" if tree.parents[1] == ROOT else tree.parents[1].name: tree.parents[1]
    for tree in source_trees()
}


def source_root(project: Path) -> Path:
    """Where a project folder of the workspace keeps the kit's modules."""
    return project / "src" / PACKAGE_NAME


def shared_init_files(packages: Mapping[str, Path] = PACKAGES) -> dict[str, list[str]]:
    """The `__init__.py` paths, relative to each package's source root, that two or more of
    `packages` (name to project folder) ship, each with the names of the packages shipping it;
    empty when no folder's `__init__.py` is doubled."""
    owners: dict[str, list[str]] = {}
    for name, project in packages.items():
        root = source_root(project)
        for init in sorted(root.rglob("__init__.py")):
            owners.setdefault(init.relative_to(root).as_posix(), []).append(name)
    return {path: names for path, names in owners.items() if len(names) > 1}
