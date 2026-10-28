"""Test support: the tracked files a repo-wide guard reads, left free of planning content.

Planning content (the specification folder, the state folder) records history and requirements,
so a guard that polices documents and code does not read it. The planning folders come from the
checkout's `abk.yaml`, never from literals in a guard.
"""

from collections.abc import Collection
from pathlib import Path

import yaml

from agent_build_kit.config import PlanningConfig
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.shell import git

ROOT = Path(__file__).resolve().parents[1]
# Vendored and built folders, skipped wherever they sit below the folder a guard reads.
SKIPPED_DIRS = frozenset({"node_modules", ".venv", "__pycache__", "dist"})
LISTING_RETRIES = 3
BUILT_WEB = Path("src/agent_build_kit/serve/static")


class PlanningDirs(Frozen):
    specs_dir: str
    state_dir: str


def planning_dirs(root: Path) -> PlanningDirs:
    """The specification and state folders of `root`'s `abk.yaml`; the default specification
    folder of `PlanningConfig` and the legacy `runs` state folder where the file, the section or
    the key is absent."""
    defaults = PlanningConfig()
    try:
        loaded = yaml.safe_load((root / "abk.yaml").read_text())
    except (OSError, yaml.YAMLError):
        loaded = None
    section = loaded.get("planning") if isinstance(loaded, dict) else None
    section = section if isinstance(section, dict) else {}
    return PlanningDirs(
        specs_dir=str(section.get("specs_dir") or defaults.specs_dir),
        state_dir=str(section.get("state_dir") or "runs"),
    )


def tracked(root: Path) -> list[Path]:
    """The paths under `root` git tracks, relative to it; the walked tree outside a repository.
    Inside one a failed listing is tried again and then raised, never answered with the walked
    tree, which holds files git does not track."""
    listed = git(root, "ls-files", "-z", check=False)
    if listed.returncode != 0 and (
        git(root, "rev-parse", "--is-inside-work-tree", check=False).returncode != 0
    ):
        return [path.relative_to(root) for path in root.rglob("*") if path.is_file()]
    for _ in range(LISTING_RETRIES):
        if listed.returncode == 0:
            break
        listed = git(root, "ls-files", "-z", check=False)
    listed.check_returncode()
    return [Path(name) for name in listed.stdout.split("\0") if name]


def skipped(path: Path, below: Path) -> bool:
    parts = path.relative_to(below).parts[:-1]
    return any(part.startswith(".") or part in SKIPPED_DIRS for part in parts) or (
        BUILT_WEB in (path, *path.parents)
    )


def guarded_files(
    root: Path = ROOT,
    *,
    under: Collection[str] = (),
    names: Collection[str] = (),
    suffixes: Collection[str] | None = None,
    specs: bool = False,
    dirs: PlanningDirs | None = None,
) -> list[Path]:
    """The tracked files below each folder of `under` (the whole tree when empty), plus the root
    files of `names` that exist, filtered by `suffixes` when given. The specification folder is
    left out unless `specs`; the state folder is always left out (name a file of it in `names`).
    Hidden, vendored and built folders below a folder of `under` are skipped. Sorted. A caller that
    already read the planning folders passes them as `dirs`."""
    dirs = dirs or planning_dirs(root)
    left_out = [Path(dirs.state_dir)] + ([] if specs else [Path(dirs.specs_dir)])
    found: set[Path] = set()
    for relative in tracked(root):
        if any(folder in (relative, *relative.parents) for folder in left_out):
            continue
        for top in [Path(name) for name in under] or [Path()]:
            if top in relative.parents and not skipped(relative, top):
                found.add(root / relative)
                break
    found.update(root / name for name in names if (root / name).is_file())
    return sorted(path for path in found if suffixes is None or path.suffix in suffixes)
